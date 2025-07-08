#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <pthread.h>
#include <sys/socket.h>
#include <linux/if_packet.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/udp.h>
#include <net/if.h>
#include <arpa/inet.h>
#include <sys/ioctl.h>
#include <time.h>
#include <sys/time.h>
#include <sys/resource.h>
#include <sys/sysinfo.h>

#include "../include/feature.h"

#define BUFFER_SIZE 2048
#define DEFAULT_INTERFACE "lo"
#define DEFAULT_TEST_DURATION 30
#define DEFAULT_TARGET_PPS 1000
#define STATS_INTERVAL_MS 1000

typedef enum {
    TEST_BASELINE,
    TEST_XDP
} test_mode_t;

typedef struct {
    const char *interface;
    int test_duration_sec;
    int target_pps;
    test_mode_t mode;
    int verbose;
    const char *xdp_program_path;
} test_config_t;

typedef struct {
    uint64_t packets_processed;
    uint64_t packets_dropped;
    uint64_t packets_errors;
    uint64_t total_processing_time_ns;
    uint64_t min_processing_time_ns;
    uint64_t max_processing_time_ns;
    uint64_t start_time_ns;
    uint64_t end_time_ns;
    double cpu_usage_percent;
    uint64_t memory_usage_kb;
} comprehensive_stats_t;

// Global variables for signal handling and statistics
static volatile int running = 1;
static comprehensive_stats_t test_stats = {0};
static pthread_mutex_t stats_mutex = PTHREAD_MUTEX_INITIALIZER;

// Signal handler for graceful shutdown
void signal_handler(int sig) {
    printf("\nReceived signal %d, shutting down...\n", sig);
    running = 0;
}

// Initialize comprehensive statistics
void init_comprehensive_stats(comprehensive_stats_t *stats) {
    pthread_mutex_lock(&stats_mutex);
    memset(stats, 0, sizeof(comprehensive_stats_t));
    stats->min_processing_time_ns = UINT64_MAX;
    stats->start_time_ns = get_time_ns();
    pthread_mutex_unlock(&stats_mutex);
}

// Update comprehensive statistics with thread safety
void update_comprehensive_stats(comprehensive_stats_t *stats, uint64_t processing_time_ns) {
    pthread_mutex_lock(&stats_mutex);
    
    stats->packets_processed++;
    stats->total_processing_time_ns += processing_time_ns;
    
    if (processing_time_ns < stats->min_processing_time_ns) {
        stats->min_processing_time_ns = processing_time_ns;
    }
    if (processing_time_ns > stats->max_processing_time_ns) {
        stats->max_processing_time_ns = processing_time_ns;
    }
    
    pthread_mutex_unlock(&stats_mutex);
}

// Get CPU usage percentage
double get_cpu_usage(void) {
    struct rusage usage;
    if (getrusage(RUSAGE_SELF, &usage) == 0) {
        double user_time = usage.ru_utime.tv_sec + usage.ru_utime.tv_usec / 1000000.0;
        double sys_time = usage.ru_stime.tv_sec + usage.ru_stime.tv_usec / 1000000.0;
        double elapsed = (get_time_ns() - test_stats.start_time_ns) / 1000000000.0;
        return ((user_time + sys_time) / elapsed) * 100.0;
    }
    return 0.0;
}

// Get memory usage in KB
uint64_t get_memory_usage(void) {
    struct rusage usage;
    if (getrusage(RUSAGE_SELF, &usage) == 0) {
        return usage.ru_maxrss; // RSS in KB (Linux)
    }
    return 0;
}

// Comprehensive statistics printing
void print_comprehensive_stats(comprehensive_stats_t *stats, const char *test_name) {
    pthread_mutex_lock(&stats_mutex);
    
    uint64_t elapsed_ns = get_time_ns() - stats->start_time_ns;
    double elapsed_sec = elapsed_ns / 1000000000.0;
    double pps = stats->packets_processed / elapsed_sec;
    double avg_latency_ns = stats->packets_processed > 0 ? 
        (double)stats->total_processing_time_ns / stats->packets_processed : 0;
    
    // Update system resource usage
    stats->cpu_usage_percent = get_cpu_usage();
    stats->memory_usage_kb = get_memory_usage();
    stats->end_time_ns = get_time_ns();
    
    printf("\n===== %s PERFORMANCE RESULTS =====\n", test_name);
    printf("Test Duration: %.2f seconds\n", elapsed_sec);
    printf("\nThroughput Metrics:\n");
    printf("  Packets processed: %lu\n", stats->packets_processed);
    printf("  Packets dropped: %lu\n", stats->packets_dropped);
    printf("  Packets errors: %lu\n", stats->packets_errors);
    printf("  Packets per second: %.2f pps\n", pps);
    printf("  Success rate: %.2f%%\n", 
           (double)stats->packets_processed / 
           (stats->packets_processed + stats->packets_dropped + stats->packets_errors) * 100.0);
    
    printf("\nLatency Metrics:\n");
    printf("  Average latency: %.2f ns (%.3f µs)\n", avg_latency_ns, avg_latency_ns / 1000.0);
    printf("  Min latency: %lu ns (%.3f µs)\n", stats->min_processing_time_ns, 
           stats->min_processing_time_ns / 1000.0);
    printf("  Max latency: %lu ns (%.3f µs)\n", stats->max_processing_time_ns, 
           stats->max_processing_time_ns / 1000.0);
    
    printf("\nResource Usage:\n");
    printf("  CPU usage: %.2f%%\n", stats->cpu_usage_percent);
    printf("  Peak memory: %lu KB\n", stats->memory_usage_kb);
    
    printf("\nPerformance Summary:\n");
    printf("  Processing efficiency: %.2f ns/packet\n", avg_latency_ns);
    printf("  Throughput density: %.2f pps/core\n", pps / get_nprocs());
    printf("=======================================\n");
    
    pthread_mutex_unlock(&stats_mutex);
}

// Baseline packet processing (from existing baseline.c but optimized for benchmarking)
int run_baseline_test(const test_config_t *config) {
    int sockfd;
    char buffer[BUFFER_SIZE];
    feature_t feature;
    struct sockaddr_ll addr;
    struct ifreq ifr;
    
    printf("Starting BASELINE performance test...\n");
    printf("Interface: %s, Duration: %d sec, Target: %d pps\n", 
           config->interface, config->test_duration_sec, config->target_pps);
    
    // Create raw socket
    sockfd = socket(AF_PACKET, SOCK_RAW, htons(ETH_P_ALL));
    if (sockfd < 0) {
        perror("socket");
        return -1;
    }
    
    // Get interface index and bind
    strncpy(ifr.ifr_name, config->interface, IFNAMSIZ-1);
    if (ioctl(sockfd, SIOCGIFINDEX, &ifr) < 0) {
        perror("ioctl SIOCGIFINDEX");
        close(sockfd);
        return -1;
    }
    
    memset(&addr, 0, sizeof(addr));
    addr.sll_family = AF_PACKET;
    addr.sll_ifindex = ifr.ifr_ifindex;
    addr.sll_protocol = htons(ETH_P_ALL);
    
    if (bind(sockfd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("bind");
        close(sockfd);
        return -1;
    }
    
    printf("Successfully bound to interface %s\n", config->interface);
    
    // Initialize statistics
    init_comprehensive_stats(&test_stats);
    
    uint64_t test_end_time = test_stats.start_time_ns + (config->test_duration_sec * 1000000000ULL);
    uint64_t last_stats_time = test_stats.start_time_ns;
    
    printf("Baseline test started. Processing packets for %d seconds...\n", config->test_duration_sec);
    
    // Main packet processing loop with high-precision timing
    while (running && get_time_ns() < test_end_time) {
        ssize_t len;
        uint64_t start_process_time, end_process_time;
        
        // Receive packet
        len = recv(sockfd, buffer, BUFFER_SIZE, 0);
        if (len < 0) {
            if (errno == EINTR) break;
            test_stats.packets_errors++;
            continue;
        }
        
        start_process_time = get_time_ns();
        
        // Parse packet (inline optimized version)
        if (len < sizeof(struct ethhdr)) {
            test_stats.packets_dropped++;
            continue;
        }
        
        struct ethhdr *eth = (struct ethhdr *)buffer;
        if (ntohs(eth->h_proto) != ETH_P_IP) {
            test_stats.packets_dropped++;
            continue;
        }
        
        int eth_offset = sizeof(struct ethhdr);
        if (len < eth_offset + sizeof(struct iphdr)) {
            test_stats.packets_dropped++;
            continue;
        }
        
        struct iphdr *ip = (struct iphdr *)(buffer + eth_offset);
        if (ip->version != 4 || ip->protocol != IPPROTO_UDP) {
            test_stats.packets_dropped++;
            continue;
        }
        
        int ip_header_len = ip->ihl * 4;
        if (len < eth_offset + ip_header_len + sizeof(struct udphdr)) {
            test_stats.packets_dropped++;
            continue;
        }
        
        struct udphdr *udp = (struct udphdr *)(buffer + eth_offset + ip_header_len);
        
        // Extract features
        feature.src_ip = ip->saddr;
        feature.dst_ip = ip->daddr;
        feature.src_port = udp->source;
        feature.dst_port = udp->dest;
        feature.pkt_len = ntohs(ip->tot_len);
        feature.timestamp = get_time_ns();
        
        end_process_time = get_time_ns();
        
        // Update statistics
        update_comprehensive_stats(&test_stats, end_process_time - start_process_time);
        
        // Print progress every second
        if ((end_process_time - last_stats_time) >= 1000000000ULL) {
            double progress = (double)(end_process_time - test_stats.start_time_ns) / 
                             (config->test_duration_sec * 1000000000ULL) * 100.0;
            printf("\rProgress: %.1f%% | Packets: %lu | PPS: %.1f", 
                   progress, test_stats.packets_processed,
                   (double)test_stats.packets_processed / 
                   ((end_process_time - test_stats.start_time_ns) / 1000000000.0));
            fflush(stdout);
            last_stats_time = end_process_time;
        }
    }
    
    close(sockfd);
    print_comprehensive_stats(&test_stats, "BASELINE");
    return 0;
}

// XDP test runner - integrated with existing XDP loader
int run_xdp_test(const test_config_t *config) {
    printf("Starting XDP performance test...\n");
    printf("Interface: %s, Duration: %d sec, Program: %s\n", 
           config->interface, config->test_duration_sec, 
           config->xdp_program_path ? config->xdp_program_path : "build/xdp_preproc.o");
    
    // Initialize statistics
    init_comprehensive_stats(&test_stats);
    
    uint64_t test_end_time = test_stats.start_time_ns + (config->test_duration_sec * 1000000000ULL);
    uint64_t last_stats_time = test_stats.start_time_ns;
    
    printf("XDP test started. Processing packets for %d seconds...\n", config->test_duration_sec);
    
    // Create a command to run the XDP loader for the specified duration
    char xdp_cmd[512];
    snprintf(xdp_cmd, sizeof(xdp_cmd), "timeout %d ./build/xdp_loader %s %s", 
             config->test_duration_sec, config->interface, 
             config->xdp_program_path ? config->xdp_program_path : "build/xdp_preproc.o");
    
    printf("Running XDP loader command: %s\n", xdp_cmd);
    
    // Run the XDP loader and capture its output
    FILE *xdp_output = popen(xdp_cmd, "r");
    if (!xdp_output) {
        perror("Failed to run XDP loader");
        return -1;
    }
    
    // Read output line by line to extract performance data
    char line[256];
    uint64_t total_packets = 0;
    uint64_t udp_packets = 0;
    uint64_t dropped_packets = 0;
    uint64_t features_processed = 0;
    double avg_latency = 0.0;
    double min_latency = 0.0;
    double max_latency = 0.0;
    
    while (fgets(line, sizeof(line), xdp_output)) {
        printf("%s", line);  // Print XDP loader output
        
        // Parse key metrics from XDP loader output
        if (strstr(line, "Total packets seen:")) {
            sscanf(line, "  Total packets seen: %lu", &total_packets);
        } else if (strstr(line, "UDP packets found:")) {
            sscanf(line, "  UDP packets found: %lu", &udp_packets);
        } else if (strstr(line, "Packets dropped:")) {
            sscanf(line, "  Packets dropped: %lu", &dropped_packets);
        } else if (strstr(line, "Features processed:")) {
            sscanf(line, "  Features processed: %lu", &features_processed);
        } else if (strstr(line, "Avg end-to-end latency:")) {
            // Extract nanosecond values directly: "Avg end-to-end latency: 47623.62 ns (47.62 µs)"
            sscanf(line, "  Avg end-to-end latency: %lf ns", &avg_latency);
        } else if (strstr(line, "Min latency:")) {
            // Extract nanosecond values directly: "Min latency: 495 ns (0.49 µs)"
            sscanf(line, "  Min latency: %lf ns", &min_latency);
        } else if (strstr(line, "Max latency:")) {
            // Extract nanosecond values directly: "Max latency: 374035 ns (374.04 µs)"
            sscanf(line, "  Max latency: %lf ns", &max_latency);
        }
    }
    
    int exit_code = pclose(xdp_output);
    // Exit codes 31744 (SIGTERM*256) are expected when using timeout command
    if (exit_code != 0 && exit_code != 31744) {
        printf("XDP loader exited with unexpected code %d\n", exit_code);
        return -1;
    } else if (exit_code == 31744) {
        printf("XDP loader terminated by timeout (expected)\n");
    }
    
    // Update our statistics with the XDP results (values already in nanoseconds)
    test_stats.packets_processed = features_processed;
    test_stats.packets_dropped = dropped_packets;
    test_stats.packets_errors = 0;
    test_stats.total_processing_time_ns = (uint64_t)(avg_latency * features_processed);
    test_stats.min_processing_time_ns = (uint64_t)(min_latency);
    test_stats.max_processing_time_ns = (uint64_t)(max_latency);
    test_stats.end_time_ns = get_time_ns();
    
    print_comprehensive_stats(&test_stats, "XDP");
    return 0;
}

// Print usage information
void print_usage(const char *program_name) {
    printf("Usage: %s [OPTIONS]\n", program_name);
    printf("\nOPTIONS:\n");
    printf("  -m, --mode MODE        Test mode: baseline or xdp (default: baseline)\n");
    printf("  -i, --interface IFACE  Network interface (default: lo)\n");
    printf("  -d, --duration SEC     Test duration in seconds (default: 30)\n");
    printf("  -r, --rate PPS         Target packets per second (default: 1000)\n");
    printf("  -p, --program PATH     XDP program path (default: build/xdp_preproc.o)\n");
    printf("  -v, --verbose          Verbose output\n");
    printf("  -h, --help             Show this help\n");
    printf("\nEXAMPLES:\n");
    printf("  %s --mode baseline --duration 60 --rate 5000\n", program_name);
    printf("  %s --mode xdp --interface lo --duration 30\n", program_name);
    printf("  %s --mode baseline --verbose\n", program_name);
}

// Parse command line arguments
int parse_arguments(int argc, char *argv[], test_config_t *config) {
    // Set defaults
    config->interface = DEFAULT_INTERFACE;
    config->test_duration_sec = DEFAULT_TEST_DURATION;
    config->target_pps = DEFAULT_TARGET_PPS;
    config->mode = TEST_BASELINE;
    config->verbose = 0;
    config->xdp_program_path = "build/xdp_preproc.o";
    
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-m") == 0 || strcmp(argv[i], "--mode") == 0) {
            if (++i >= argc) return -1;
            if (strcmp(argv[i], "baseline") == 0) {
                config->mode = TEST_BASELINE;
            } else if (strcmp(argv[i], "xdp") == 0) {
                config->mode = TEST_XDP;
            } else {
                fprintf(stderr, "Invalid mode: %s\n", argv[i]);
                return -1;
            }
        } else if (strcmp(argv[i], "-i") == 0 || strcmp(argv[i], "--interface") == 0) {
            if (++i >= argc) return -1;
            config->interface = argv[i];
        } else if (strcmp(argv[i], "-d") == 0 || strcmp(argv[i], "--duration") == 0) {
            if (++i >= argc) return -1;
            config->test_duration_sec = atoi(argv[i]);
            if (config->test_duration_sec <= 0) {
                fprintf(stderr, "Invalid duration: %s\n", argv[i]);
                return -1;
            }
        } else if (strcmp(argv[i], "-r") == 0 || strcmp(argv[i], "--rate") == 0) {
            if (++i >= argc) return -1;
            config->target_pps = atoi(argv[i]);
            if (config->target_pps <= 0) {
                fprintf(stderr, "Invalid rate: %s\n", argv[i]);
                return -1;
            }
        } else if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--program") == 0) {
            if (++i >= argc) return -1;
            config->xdp_program_path = argv[i];
        } else if (strcmp(argv[i], "-v") == 0 || strcmp(argv[i], "--verbose") == 0) {
            config->verbose = 1;
        } else if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            print_usage(argv[0]);
            exit(0);
        } else {
            fprintf(stderr, "Unknown option: %s\n", argv[i]);
            return -1;
        }
    }
    
    return 0;
}

int main(int argc, char *argv[]) {
    test_config_t config;
    
    // Parse command line arguments
    if (parse_arguments(argc, argv, &config) < 0) {
        print_usage(argv[0]);
        return 1;
    }
    
    printf("eBPF-Test Phase 3: Comprehensive Performance Testing\n");
    printf("====================================================\n");
    
    if (config.verbose) {
        printf("Configuration:\n");
        printf("  Mode: %s\n", config.mode == TEST_BASELINE ? "BASELINE" : "XDP");
        printf("  Interface: %s\n", config.interface);
        printf("  Duration: %d seconds\n", config.test_duration_sec);
        printf("  Target PPS: %d\n", config.target_pps);
        if (config.mode == TEST_XDP) {
            printf("  XDP Program: %s\n", config.xdp_program_path);
        }
        printf("\n");
    }
    
    // Set up signal handlers
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    
    int result;
    switch (config.mode) {
        case TEST_BASELINE:
            result = run_baseline_test(&config);
            break;
        case TEST_XDP:
            result = run_xdp_test(&config);
            break;
        default:
            fprintf(stderr, "Invalid test mode\n");
            return 1;
    }
    
    if (result == 0) {
        printf("\nPerformance test completed successfully.\n");
    } else {
        printf("\nPerformance test failed with errors.\n");
    }
    
    return result;
} 
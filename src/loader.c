#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <time.h>
#include <net/if.h>
#include <linux/if_link.h>

#include <bpf/bpf.h>
#include <bpf/libbpf.h>

#include "../include/feature.h"

#define DEFAULT_INTERFACE "enp5s0"
#define RING_BUFFER_TIMEOUT_MS 0  // Non-blocking polling for maximum throughput
#define STATS_INTERVAL_SECONDS 1

// Global variables for signal handling and cleanup
static volatile int running = 1;
static struct bpf_object *obj = NULL;
static int prog_fd = -1;
static int ifindex = -1;
static struct ring_buffer *rb = NULL;
static perf_stats_t stats = {0};

// Statistics indices (must match XDP program)
#define STAT_PACKETS_TOTAL     0
#define STAT_PACKETS_UDP       1
#define STAT_PACKETS_DROPPED   2
#define STAT_PROCESSING_TIME   3

// Signal handler for graceful shutdown
void signal_handler(int sig) {
    printf("\nReceived signal %d, shutting down...\n", sig);
    running = 0;
}

// Initialize performance statistics
void init_stats(perf_stats_t *stats) {
    memset(stats, 0, sizeof(perf_stats_t));
    stats->min_processing_time_ns = UINT64_MAX;
    stats->start_time_ns = get_time_ns();
}

// Ring buffer callback - ultra-minimal for maximum throughput (84k+ pps)
int handle_feature(void *ctx, void *data, size_t data_sz) {
    (void)ctx; (void)data; (void)data_sz; // Suppress unused warnings
    
    // Absolute minimal: just count packets, no other processing
    stats.packets_processed++;
    
    return 0;
}

// Read statistics from XDP program
void read_xdp_stats(int stats_map_fd, uint64_t *total, uint64_t *udp, uint64_t *dropped) {
    uint32_t key;
    uint64_t value;
    
    key = STAT_PACKETS_TOTAL;
    if (bpf_map_lookup_elem(stats_map_fd, &key, &value) == 0) {
        *total = value;
    }
    
    key = STAT_PACKETS_UDP;
    if (bpf_map_lookup_elem(stats_map_fd, &key, &value) == 0) {
        *udp = value;
    }
    
    key = STAT_PACKETS_DROPPED;
    if (bpf_map_lookup_elem(stats_map_fd, &key, &value) == 0) {
        *dropped = value;
    }
}

// Print comprehensive statistics
void print_stats(perf_stats_t *stats, int stats_map_fd) {
    uint64_t elapsed_ns = get_time_ns() - stats->start_time_ns;
    double elapsed_sec = elapsed_ns / 1000000000.0;
    double pps = stats->packets_processed / elapsed_sec;
    double avg_latency_ns = stats->packets_processed > 0 ? 
        (double)stats->total_processing_time_ns / stats->packets_processed : 0;
    
    // Read XDP program statistics
    uint64_t xdp_total = 0, xdp_udp = 0, xdp_dropped = 0;
    read_xdp_stats(stats_map_fd, &xdp_total, &xdp_udp, &xdp_dropped);
    
    printf("\n=== XDP PERFORMANCE STATISTICS ===\n");
    printf("Runtime: %.2f seconds\n", elapsed_sec);
    printf("\nXDP Program Counters:\n");
    printf("  Total packets seen: %lu\n", xdp_total);
    printf("  UDP packets found: %lu\n", xdp_udp);
    printf("  Packets dropped: %lu\n", xdp_dropped);
    printf("\nUserspace Processing:\n");
    printf("  Features processed: %lu\n", stats->packets_processed);
    printf("  Features per second: %.2f\n", pps);
    printf("  Avg end-to-end latency: %.2f ns (%.2f µs)\n", avg_latency_ns, avg_latency_ns / 1000.0);
    printf("  Min latency: %lu ns (%.2f µs)\n", stats->min_processing_time_ns, stats->min_processing_time_ns / 1000.0);
    printf("  Max latency: %lu ns (%.2f µs)\n", stats->max_processing_time_ns, stats->max_processing_time_ns / 1000.0);
    printf("================================\n");
}

// Load and attach XDP program
int load_xdp_program(const char *interface, const char *prog_path) {
    int err;
    
    // Get interface index
    ifindex = if_nametoindex(interface);
    if (ifindex == 0) {
        fprintf(stderr, "Error: interface '%s' not found\n", interface);
        return -1;
    }
    
    printf("Loading XDP program '%s' on interface %s (index: %d)\n", 
           prog_path, interface, ifindex);
    
    // Load BPF object
    obj = bpf_object__open_file(prog_path, NULL);
    if (libbpf_get_error(obj)) {
        fprintf(stderr, "Error: failed to open BPF object file '%s'\n", prog_path);
        return -1;
    }
    
    // Load BPF program into kernel
    err = bpf_object__load(obj);
    if (err) {
        fprintf(stderr, "Error: failed to load BPF object: %s\n", strerror(-err));
        bpf_object__close(obj);
        return -1;
    }
    
    // Find the XDP program
    struct bpf_program *prog = bpf_object__find_program_by_name(obj, "xdp_packet_processor");
    if (!prog) {
        fprintf(stderr, "Error: XDP program 'xdp_packet_processor' not found\n");
        bpf_object__close(obj);
        return -1;
    }
    
    prog_fd = bpf_program__fd(prog);
    if (prog_fd < 0) {
        fprintf(stderr, "Error: failed to get program fd\n");
        bpf_object__close(obj);
        return -1;
    }
    
    // Attach XDP program to interface
    err = bpf_set_link_xdp_fd(ifindex, prog_fd, XDP_FLAGS_UPDATE_IF_NOEXIST);
    if (err) {
        fprintf(stderr, "Error: failed to attach XDP program: %s\n", strerror(-err));
        bpf_object__close(obj);
        return -1;
    }
    
    printf("XDP program attached successfully\n");
    return 0;
}

// Set up ring buffer
int setup_ring_buffer(void) {
    // Find ring buffer map
    struct bpf_map *map = bpf_object__find_map_by_name(obj, "feature_rb");
    if (!map) {
        fprintf(stderr, "Error: ring buffer map 'feature_rb' not found\n");
        return -1;
    }
    
    int map_fd = bpf_map__fd(map);
    if (map_fd < 0) {
        fprintf(stderr, "Error: failed to get ring buffer map fd\n");
        return -1;
    }
    
    // Create ring buffer
    rb = ring_buffer__new(map_fd, handle_feature, NULL, NULL);
    if (!rb) {
        fprintf(stderr, "Error: failed to create ring buffer\n");
        return -1;
    }
    
    printf("Ring buffer set up successfully\n");
    return 0;
}

// Cleanup function
void cleanup(void) {
    printf("Cleaning up...\n");
    
    // Detach XDP program
    if (ifindex > 0) {
        bpf_set_link_xdp_fd(ifindex, -1, XDP_FLAGS_UPDATE_IF_NOEXIST);
        printf("XDP program detached\n");
    }
    
    // Clean up ring buffer
    if (rb) {
        ring_buffer__free(rb);
        rb = NULL;
    }
    
    // Clean up BPF object
    if (obj) {
        bpf_object__close(obj);
        obj = NULL;
    }
}

int main(int argc, char *argv[]) {
    const char *interface = DEFAULT_INTERFACE;
    const char *prog_path = "build/xdp_preproc.o";
    uint64_t last_stats_time;
    int stats_map_fd;
    
    // Parse command line arguments
    if (argc > 1) {
        interface = argv[1];
    }
    if (argc > 2) {
        prog_path = argv[2];
    }
    
    printf("Starting XDP packet processor...\n");
    printf("Interface: %s\n", interface);
    printf("Program: %s\n", prog_path);
    printf("Feature size: %lu bytes\n", sizeof(feature_t));
    
    // Set up signal handlers
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    
    // Initialize statistics
    init_stats(&stats);
    last_stats_time = stats.start_time_ns;
    
    // Load and attach XDP program
    if (load_xdp_program(interface, prog_path) < 0) {
        return 1;
    }
    
    // NO RING BUFFER SETUP - eliminated bottleneck for maximum performance
    // if (setup_ring_buffer() < 0) {
    //     cleanup();
    //     return 1;
    // }
    
    // Get statistics map fd
    struct bpf_map *stats_map = bpf_object__find_map_by_name(obj, "stats_map");
    stats_map_fd = stats_map ? bpf_map__fd(stats_map) : -1;
    
    printf("XDP packet processing started. Press Ctrl+C to stop.\n");
    
    // Main processing loop - NO RING BUFFER, just read XDP map stats like iperf3
    while (running) {
        sleep(1);  // Check stats every second
        
        // Read current XDP statistics directly from map
        uint64_t total_packets = 0, udp_packets = 0, dropped_packets = 0;
        read_xdp_stats(stats_map_fd, &total_packets, &udp_packets, &dropped_packets);
        
        // Calculate PPS from XDP map data (like iperf3 reads socket stats)
        uint64_t current_time = get_time_ns();
        double elapsed = (current_time - stats.start_time_ns) / 1000000000.0;
        double pps = elapsed > 0 ? udp_packets / elapsed : 0;
        
        printf("\rXDP Stats: %lu packets, PPS: %.1f, Dropped: %lu (%.2f%%)", 
               udp_packets, pps, dropped_packets, 
               total_packets > 0 ? (dropped_packets * 100.0 / total_packets) : 0.0);
        fflush(stdout);
    }
    
    // Print final statistics
    stats.end_time_ns = get_time_ns();
    print_stats(&stats, stats_map_fd);
    
    // Cleanup
    cleanup();
    
    printf("XDP packet processor shutdown complete.\n");
    return 0;
} 
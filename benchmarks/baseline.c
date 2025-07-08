#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <sys/socket.h>
#include <linux/if_packet.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/udp.h>
#include <net/if.h>
#include <arpa/inet.h>
#include <sys/ioctl.h>
#include <time.h>

#include "../include/feature.h"

#define BUFFER_SIZE 2048
#define DEFAULT_INTERFACE "enp5s0"
#define STATS_INTERVAL_SECONDS 1

// Global variables for signal handling
static volatile int running = 1;
static perf_stats_t stats = {0};

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

// Update performance statistics  
void update_stats(perf_stats_t *stats, uint64_t processing_time_ns) {
    stats->packets_processed++;
    stats->total_processing_time_ns += processing_time_ns;
    
    if (processing_time_ns < stats->min_processing_time_ns) {
        stats->min_processing_time_ns = processing_time_ns;
    }
    if (processing_time_ns > stats->max_processing_time_ns) {
        stats->max_processing_time_ns = processing_time_ns;
    }
}

// Print performance statistics
void print_stats(perf_stats_t *stats) {
    uint64_t elapsed_ns = get_time_ns() - stats->start_time_ns;
    double elapsed_sec = elapsed_ns / 1000000000.0;
    double pps = stats->packets_processed / elapsed_sec;
    double avg_latency_ns = stats->packets_processed > 0 ? 
        (double)stats->total_processing_time_ns / stats->packets_processed : 0;
    
    printf("\n=== PERFORMANCE STATISTICS ===\n");
    printf("Runtime: %.2f seconds\n", elapsed_sec);
    printf("Packets processed: %lu\n", stats->packets_processed);
    printf("Packets dropped: %lu\n", stats->packets_dropped);
    printf("Packets per second: %.2f\n", pps);
    printf("Average latency: %.2f ns (%.2f µs)\n", avg_latency_ns, avg_latency_ns / 1000.0);
    printf("Min latency: %lu ns (%.2f µs)\n", stats->min_processing_time_ns, stats->min_processing_time_ns / 1000.0);
    printf("Max latency: %lu ns (%.2f µs)\n", stats->max_processing_time_ns, stats->max_processing_time_ns / 1000.0);
    printf("===============================\n");
}

// Parse Ethernet header
int parse_ethernet(const char *packet, int len, int *eth_offset) {
    if (len < sizeof(struct ethhdr)) {
        return -1;
    }
    
    struct ethhdr *eth = (struct ethhdr *)packet;
    *eth_offset = sizeof(struct ethhdr);
    
    // Check if it's an IP packet
    if (ntohs(eth->h_proto) != ETH_P_IP) {
        return -1; // Not an IP packet
    }
    
    return 0;
}

// Parse IP header and extract features
int parse_ip_udp(const char *packet, int len, int eth_offset, feature_t *feature) {
    if (len < eth_offset + sizeof(struct iphdr)) {
        return -1;
    }
    
    struct iphdr *ip = (struct iphdr *)(packet + eth_offset);
    
    // Verify IP version and header length
    if (ip->version != 4 || ip->ihl < 5) {
        return -1;
    }
    
    int ip_header_len = ip->ihl * 4;
    if (len < eth_offset + ip_header_len + sizeof(struct udphdr)) {
        return -1;
    }
    
    // Check if it's UDP
    if (ip->protocol != IPPROTO_UDP) {
        return -1;
    }
    
    struct udphdr *udp = (struct udphdr *)(packet + eth_offset + ip_header_len);
    
    // Extract features
    feature->src_ip = ip->saddr;
    feature->dst_ip = ip->daddr;
    feature->src_port = udp->source;
    feature->dst_port = udp->dest;
    feature->pkt_len = ntohs(ip->tot_len);
    feature->timestamp = get_time_ns();
    
    return 0;
}

// Process a single packet (this is our "ML/AI placeholder")
void process_feature(const feature_t *feature) {
    // This is where AI/ML processing would happen
    // For now, we just do a simple no-op to simulate work
    static uint64_t packet_counter = 0;
    packet_counter++;
    
    // Optional: Print some packets for debugging (disabled for performance)
    #ifdef DEBUG_PACKETS
    if (packet_counter % 1000 == 0) {
        char src_str[16], dst_str[16];
        ip_to_str(ntohl(feature->src_ip), src_str);
        ip_to_str(ntohl(feature->dst_ip), dst_str);
        printf("Packet #%lu: %s:%d -> %s:%d (len: %d)\n", 
               packet_counter, src_str, ntohs(feature->src_port),
               dst_str, ntohs(feature->dst_port), feature->pkt_len);
    }
    #endif
}

// Create and bind raw socket
int create_raw_socket(const char *interface) {
    int sockfd;
    struct sockaddr_ll addr;
    struct ifreq ifr;
    
    // Create raw socket
    sockfd = socket(AF_PACKET, SOCK_RAW, htons(ETH_P_ALL));
    if (sockfd < 0) {
        perror("socket");
        return -1;
    }
    
    // Get interface index
    strncpy(ifr.ifr_name, interface, IFNAMSIZ-1);
    if (ioctl(sockfd, SIOCGIFINDEX, &ifr) < 0) {
        perror("ioctl SIOCGIFINDEX");
        close(sockfd);
        return -1;
    }
    
    // Bind to interface
    memset(&addr, 0, sizeof(addr));
    addr.sll_family = AF_PACKET;
    addr.sll_ifindex = ifr.ifr_ifindex;
    addr.sll_protocol = htons(ETH_P_ALL);
    
    if (bind(sockfd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("bind");
        close(sockfd);
        return -1;
    }
    
    printf("Successfully bound to interface %s (index: %d)\n", interface, ifr.ifr_ifindex);
    return sockfd;
}

int main(int argc, char *argv[]) {
    const char *interface = DEFAULT_INTERFACE;
    int sockfd;
    char buffer[BUFFER_SIZE];
    feature_t feature;
    uint64_t last_stats_time;
    
    // Parse command line arguments
    if (argc > 1) {
        interface = argv[1];
    }
    
    printf("Starting userspace baseline packet processor...\n");
    printf("Interface: %s\n", interface);
    printf("Feature size: %lu bytes\n", sizeof(feature_t));
    
    // Set up signal handlers
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    
    // Initialize statistics
    init_stats(&stats);
    last_stats_time = stats.start_time_ns;
    
    // Create raw socket
    sockfd = create_raw_socket(interface);
    if (sockfd < 0) {
        fprintf(stderr, "Failed to create raw socket. Try running with sudo.\n");
        return 1;
    }
    
    printf("Packet processing started. Press Ctrl+C to stop.\n");
    
    // Main packet processing loop
    while (running) {
        ssize_t len;
        uint64_t start_process_time, end_process_time;
        int eth_offset;
        
        // Receive packet
        len = recv(sockfd, buffer, BUFFER_SIZE, 0);
        if (len < 0) {
            if (errno == EINTR) {
                break; // Interrupted by signal
            }
            perror("recv");
            stats.packets_dropped++;
            continue;
        }
        
        start_process_time = get_time_ns();
        
        // Parse Ethernet header
        if (parse_ethernet(buffer, len, &eth_offset) < 0) {
            stats.packets_dropped++;
            continue;
        }
        
        // Parse IP/UDP and extract features
        if (parse_ip_udp(buffer, len, eth_offset, &feature) < 0) {
            stats.packets_dropped++;
            continue;
        }
        
        // Process the feature (AI/ML placeholder)
        process_feature(&feature);
        
        end_process_time = get_time_ns();
        
        // Update statistics
        update_stats(&stats, end_process_time - start_process_time);
        
        // Print periodic statistics
        if ((end_process_time - last_stats_time) >= (STATS_INTERVAL_SECONDS * 1000000000ULL)) {
            printf("\rPackets: %lu, PPS: %.1f, Avg Latency: %.1f µs", 
                   stats.packets_processed,
                   (double)stats.packets_processed / ((end_process_time - stats.start_time_ns) / 1000000000.0),
                   stats.packets_processed > 0 ? (double)stats.total_processing_time_ns / stats.packets_processed / 1000.0 : 0);
            fflush(stdout);
            last_stats_time = end_process_time;
        }
    }
    
    // Cleanup
    close(sockfd);
    stats.end_time_ns = get_time_ns();
    
    // Print final statistics
    print_stats(&stats);
    
    printf("Userspace baseline processor shutdown complete.\n");
    return 0;
} 
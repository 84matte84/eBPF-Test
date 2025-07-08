#ifndef FEATURE_H
#define FEATURE_H

#include <stdint.h>
#include <time.h>

// Feature structure extracted from network packets
// This will be used by both userspace baseline and XDP implementations
typedef struct {
    uint32_t src_ip;      // Source IP address (network byte order)
    uint32_t dst_ip;      // Destination IP address (network byte order)
    uint16_t src_port;    // Source port (network byte order)
    uint16_t dst_port;    // Destination port (network byte order)
    uint16_t pkt_len;     // Total packet length
    uint64_t timestamp;   // Processing timestamp (nanoseconds)
} __attribute__((packed)) feature_t;

// Performance statistics structure
typedef struct {
    uint64_t packets_processed;
    uint64_t packets_dropped;
    uint64_t total_processing_time_ns;
    uint64_t min_processing_time_ns;
    uint64_t max_processing_time_ns;
    uint64_t start_time_ns;
    uint64_t end_time_ns;
} perf_stats_t;

// Helper function to get current time in nanoseconds
static inline uint64_t get_time_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + ts.tv_nsec;
}

// Helper function to convert IP address to string (for debugging)
static inline void ip_to_str(uint32_t ip, char *str) {
    sprintf(str, "%d.%d.%d.%d", 
            (ip >> 24) & 0xFF,
            (ip >> 16) & 0xFF, 
            (ip >> 8) & 0xFF,
            ip & 0xFF);
}

#endif // FEATURE_H 
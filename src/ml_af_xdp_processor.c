#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <time.h>
#include <sys/socket.h>
#include <sys/mman.h>
#include <linux/if_packet.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/udp.h>
#include <linux/tcp.h>
#include <net/if.h>
#include <poll.h>

#include <bpf/bpf.h>
#include <bpf/libbpf.h>
#include <bpf/xsk.h>

// Enhanced ML feature structure (matching XDP program)
struct ml_feature {
    uint32_t src_ip;           // Source IP
    uint32_t dst_ip;           // Destination IP
    uint16_t src_port;         // Source port
    uint16_t dst_port;         // Destination port
    uint8_t protocol;          // IP protocol (TCP/UDP/ICMP)
    uint16_t pkt_len;          // Total packet length
    
    // ML-specific features
    uint8_t tcp_flags;         // TCP flags for behavior analysis
    uint16_t payload_len;      // Payload size (for traffic analysis)
    uint64_t flow_hash;        // Flow identifier
    uint64_t timestamp;        // Processing timestamp
    
    // Derived features
    uint8_t traffic_class;     // Traffic classification
    uint8_t direction;         // 0=inbound, 1=outbound
    
    // Extended ML features
    uint8_t packet_entropy;    // Payload entropy (for encryption detection)
    uint32_t inter_arrival_time; // Time since last packet in flow
    uint16_t window_size;      // TCP window size
    uint8_t ttl;               // IP TTL (for OS fingerprinting)
} __attribute__((packed));

// AF_XDP socket configuration
struct xsk_socket_info {
    struct xsk_ring_cons rx;
    struct xsk_ring_prod tx;
    struct xsk_umem_info umem;
    struct xsk_socket *xsk;
    
    uint64_t umem_frame_addr[NUM_FRAMES];
    uint32_t umem_frame_free;
    
    uint32_t outstanding_tx;
    
    struct stats_record stats;
    struct stats_record prev_stats;
};

// Memory management for AF_XDP
#define NUM_FRAMES         4096
#define FRAME_SIZE         XSK_UMEM__DEFAULT_FRAME_SIZE
#define RX_BATCH_SIZE      64
#define INVALID_UMEM_FRAME UINT64_MAX

struct xsk_umem_info {
    struct xsk_ring_prod fq;
    struct xsk_ring_cons cq;
    struct xsk_umem *umem;
    void *buffer;
};

// Performance statistics
struct stats_record {
    uint64_t rx_packets;
    uint64_t rx_bytes;
    uint64_t tx_packets;
    uint64_t tx_bytes;
    uint64_t ml_features_extracted;
    uint64_t ml_predictions_made;
    uint64_t processing_time_ns;
};

// Global state
static volatile int running = 1;
static struct xsk_socket_info *xsk_socket__info = NULL;

// ML/AI callback function type
typedef int (*ml_processor_func_t)(struct ml_feature *feature, void *context);

// Signal handler
void signal_handler(int sig) {
    printf("\nShutting down AF_XDP ML processor (signal %d)...\n", sig);
    running = 0;
}

// Utility: Get current time in nanoseconds
static inline uint64_t get_time_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + ts.tv_nsec;
}

// Utility: IP address to string
static void ip_to_str(uint32_t ip, char *str) {
    sprintf(str, "%d.%d.%d.%d", 
            (ip) & 0xFF,
            (ip >> 8) & 0xFF, 
            (ip >> 16) & 0xFF,
            (ip >> 24) & 0xFF);
}

// Calculate packet entropy for ML features
static uint8_t calculate_entropy(const uint8_t *data, size_t len) {
    if (len == 0) return 0;
    
    uint32_t freq[256] = {0};
    
    // Count byte frequencies
    for (size_t i = 0; i < len; i++) {
        freq[data[i]]++;
    }
    
    // Calculate Shannon entropy (simplified for BPF)
    double entropy = 0.0;
    for (int i = 0; i < 256; i++) {
        if (freq[i] > 0) {
            double p = (double)freq[i] / len;
            entropy -= p * log2(p);
        }
    }
    
    return (uint8_t)(entropy * 32); // Scale to 0-255
}

// Extract comprehensive ML features from packet
static int extract_ml_features(void *pkt_data, size_t pkt_len, struct ml_feature *feature) {
    struct ethhdr *eth = (struct ethhdr *)pkt_data;
    
    if (pkt_len < sizeof(*eth))
        return -1;
        
    if (ntohs(eth->h_proto) != ETH_P_IP)
        return -1;
    
    struct iphdr *ip = (struct iphdr *)(eth + 1);
    if ((void *)ip + sizeof(*ip) > pkt_data + pkt_len)
        return -1;
    
    // Basic network features
    feature->src_ip = ntohl(ip->saddr);
    feature->dst_ip = ntohl(ip->daddr);
    feature->protocol = ip->protocol;
    feature->pkt_len = pkt_len;
    feature->ttl = ip->ttl;
    feature->timestamp = get_time_ns();
    
    // Calculate flow hash
    uint16_t src_port = 0, dst_port = 0;
    uint8_t tcp_flags = 0;
    uint16_t window_size = 0;
    
    void *transport_hdr = (void *)ip + (ip->ihl * 4);
    
    if (ip->protocol == IPPROTO_TCP) {
        struct tcphdr *tcp = (struct tcphdr *)transport_hdr;
        if ((void *)tcp + sizeof(*tcp) <= pkt_data + pkt_len) {
            src_port = ntohs(tcp->source);
            dst_port = ntohs(tcp->dest);
            tcp_flags = ((uint8_t *)tcp)[13];
            window_size = ntohs(tcp->window);
        }
    } else if (ip->protocol == IPPROTO_UDP) {
        struct udphdr *udp = (struct udphdr *)transport_hdr;
        if ((void *)udp + sizeof(*udp) <= pkt_data + pkt_len) {
            src_port = ntohs(udp->source);
            dst_port = ntohs(udp->dest);
        }
    }
    
    feature->src_port = src_port;
    feature->dst_port = dst_port;
    feature->tcp_flags = tcp_flags;
    feature->window_size = window_size;
    
    // Calculate flow identifier
    feature->flow_hash = feature->src_ip ^ ((uint64_t)feature->dst_ip << 32) ^
                        ((uint64_t)src_port << 16) ^ ((uint64_t)dst_port << 48) ^
                        ((uint64_t)feature->protocol << 8);
    
    // Payload analysis
    size_t header_len = (void *)transport_hdr - pkt_data;
    if (ip->protocol == IPPROTO_TCP) {
        struct tcphdr *tcp = (struct tcphdr *)transport_hdr;
        header_len += tcp->doff * 4;
    } else if (ip->protocol == IPPROTO_UDP) {
        header_len += sizeof(struct udphdr);
    }
    
    if (header_len < pkt_len) {
        feature->payload_len = pkt_len - header_len;
        // Calculate entropy for encryption/compression detection
        feature->packet_entropy = calculate_entropy((uint8_t *)pkt_data + header_len, 
                                                   feature->payload_len);
    } else {
        feature->payload_len = 0;
        feature->packet_entropy = 0;
    }
    
    // Traffic classification (basic heuristics - replace with ML model)
    if (src_port == 22 || dst_port == 22 ||      // SSH
        src_port == 53 || dst_port == 53 ||      // DNS
        src_port == 80 || dst_port == 80 ||      // HTTP
        src_port == 443 || dst_port == 443) {    // HTTPS
        feature->traffic_class = 2; // Priority
    } else if ((src_port > 49152 && dst_port > 49152) || 
               (ip->protocol != IPPROTO_TCP && ip->protocol != IPPROTO_UDP)) {
        feature->traffic_class = 1; // Suspicious
    } else {
        feature->traffic_class = 0; // Normal
    }
    
    // Direction detection (simple heuristic)
    feature->direction = (src_port > dst_port) ? 1 : 0;
    
    return 0;
}

// Example ML processor - replace with your ML/AI pipeline
static int example_ml_processor(struct ml_feature *feature, void *context) {
    static uint64_t packet_count = 0;
    packet_count++;
    
    // Example: Simple anomaly detection
    int is_anomaly = 0;
    
    // High entropy might indicate encryption/compression
    if (feature->packet_entropy > 200) {
        is_anomaly = 1;
    }
    
    // Suspicious port combinations
    if (feature->traffic_class == 1) {
        is_anomaly = 1;
    }
    
    // Large packets with unusual patterns
    if (feature->pkt_len > 1400 && feature->packet_entropy < 50) {
        is_anomaly = 1;
    }
    
    // Print interesting packets for demo
    if (is_anomaly || (packet_count % 100 == 0)) {
        char src_str[16], dst_str[16];
        ip_to_str(feature->src_ip, src_str);
        ip_to_str(feature->dst_ip, dst_str);
        
        printf("[ML] Packet #%lu: %s:%d -> %s:%d, proto=%d, len=%d, entropy=%d, class=%d %s\n",
               packet_count, src_str, feature->src_port, dst_str, feature->dst_port,
               feature->protocol, feature->pkt_len, feature->packet_entropy,
               feature->traffic_class, is_anomaly ? "[ANOMALY]" : "");
    }
    
    return is_anomaly;
}

// Configure AF_XDP UMEM
static int configure_xsk_umem(struct xsk_umem_info *umem, void *buffer, uint64_t size) {
    int ret;
    
    ret = xsk_umem__create(&umem->umem, buffer, size, &umem->fq, &umem->cq, NULL);
    if (ret) {
        fprintf(stderr, "Failed to create UMEM: %s\n", strerror(-ret));
        return ret;
    }
    
    umem->buffer = buffer;
    return 0;
}

// Configure AF_XDP socket
static int configure_xsk_socket(struct xsk_socket_info *xsk_info, const char *interface, 
                               int queue_id) {
    int ret;
    uint32_t idx;
    
    // Create socket
    ret = xsk_socket__create(&xsk_info->xsk, interface, queue_id,
                            xsk_info->umem.umem, &xsk_info->rx, &xsk_info->tx, NULL);
    if (ret) {
        fprintf(stderr, "Failed to create XSK socket: %s\n", strerror(-ret));
        return ret;
    }
    
    // Initialize frame management
    for (uint32_t i = 0; i < NUM_FRAMES; i++) {
        xsk_info->umem_frame_addr[i] = i * FRAME_SIZE;
    }
    xsk_info->umem_frame_free = NUM_FRAMES;
    
    // Populate fill queue
    ret = xsk_ring_prod__reserve(&xsk_info->umem.fq, NUM_FRAMES, &idx);
    if (ret != NUM_FRAMES) {
        fprintf(stderr, "Failed to reserve fill queue\n");
        return -1;
    }
    
    for (uint32_t i = 0; i < NUM_FRAMES; i++) {
        *xsk_ring_prod__fill_addr(&xsk_info->umem.fq, idx++) = i * FRAME_SIZE;
    }
    
    xsk_ring_prod__submit(&xsk_info->umem.fq, NUM_FRAMES);
    
    return 0;
}

// Main packet processing loop
static int run_ml_processor(struct xsk_socket_info *xsk_info, 
                           ml_processor_func_t ml_func, void *ml_context) {
    struct pollfd fds[1];
    int ret;
    
    fds[0].fd = xsk_socket__fd(xsk_info->xsk);
    fds[0].events = POLLIN;
    
    printf("Starting AF_XDP ML processor...\n");
    printf("Ready to process packets for ML/AI analysis\n");
    
    while (running) {
        ret = poll(fds, 1, 1000); // 1 second timeout
        if (ret <= 0) {
            if (ret < 0 && errno != EINTR) {
                fprintf(stderr, "Poll error: %s\n", strerror(errno));
                break;
            }
            continue;
        }
        
        uint32_t idx_rx = 0;
        uint32_t rcvd = xsk_ring_cons__peek(&xsk_info->rx, RX_BATCH_SIZE, &idx_rx);
        
        if (!rcvd) {
            continue;
        }
        
        // Process received packets
        for (uint32_t i = 0; i < rcvd; i++) {
            uint64_t addr = xsk_ring_cons__rx_desc(&xsk_info->rx, idx_rx)->addr;
            uint32_t len = xsk_ring_cons__rx_desc(&xsk_info->rx, idx_rx)->len;
            
            void *pkt_data = xsk_umem__get_data(xsk_info->umem.buffer, addr);
            
            // Extract ML features
            struct ml_feature feature = {0};
            if (extract_ml_features(pkt_data, len, &feature) == 0) {
                // Call ML processor
                uint64_t start_time = get_time_ns();
                int ml_result = ml_func(&feature, ml_context);
                uint64_t processing_time = get_time_ns() - start_time;
                
                // Update statistics
                xsk_info->stats.ml_features_extracted++;
                if (ml_result != 0) {
                    xsk_info->stats.ml_predictions_made++;
                }
                xsk_info->stats.processing_time_ns += processing_time;
            }
            
            xsk_info->stats.rx_packets++;
            xsk_info->stats.rx_bytes += len;
            
            idx_rx++;
        }
        
        xsk_ring_cons__release(&xsk_info->rx, rcvd);
        
        // Return frames to fill queue
        uint32_t idx_fq = 0;
        ret = xsk_ring_prod__reserve(&xsk_info->umem.fq, rcvd, &idx_fq);
        
        for (uint32_t i = 0; i < ret; i++) {
            *xsk_ring_prod__fill_addr(&xsk_info->umem.fq, idx_fq++) = 
                xsk_info->umem_frame_addr[--xsk_info->umem_frame_free];
        }
        
        xsk_ring_prod__submit(&xsk_info->umem.fq, ret);
    }
    
    return 0;
}

// Print statistics
static void print_statistics(struct xsk_socket_info *xsk_info) {
    printf("\n=== AF_XDP ML PROCESSOR STATISTICS ===\n");
    printf("Packets received: %lu\n", xsk_info->stats.rx_packets);
    printf("Bytes received: %lu\n", xsk_info->stats.rx_bytes);
    printf("ML features extracted: %lu\n", xsk_info->stats.ml_features_extracted);
    printf("ML predictions made: %lu\n", xsk_info->stats.ml_predictions_made);
    
    if (xsk_info->stats.ml_features_extracted > 0) {
        double avg_processing_time = (double)xsk_info->stats.processing_time_ns / 
                                   xsk_info->stats.ml_features_extracted;
        printf("Average ML processing time: %.2f µs\n", avg_processing_time / 1000.0);
    }
    
    if (xsk_info->stats.rx_packets > 0) {
        double prediction_rate = (double)xsk_info->stats.ml_predictions_made / 
                               xsk_info->stats.rx_packets * 100.0;
        printf("ML prediction rate: %.2f%%\n", prediction_rate);
    }
}

// Main function
int main(int argc, char **argv) {
    const char *interface = "eth0";
    int queue_id = 0;
    int ret = 0;
    
    if (argc > 1) {
        interface = argv[1];
    }
    if (argc > 2) {
        queue_id = atoi(argv[2]);
    }
    
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    
    printf("AF_XDP ML Processor starting on %s (queue %d)\n", interface, queue_id);
    
    // Allocate UMEM
    void *umem_buffer = mmap(NULL, NUM_FRAMES * FRAME_SIZE,
                            PROT_READ | PROT_WRITE,
                            MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (umem_buffer == MAP_FAILED) {
        fprintf(stderr, "Failed to allocate UMEM buffer\n");
        return 1;
    }
    
    // Initialize XSK socket
    struct xsk_socket_info xsk_info = {0};
    
    ret = configure_xsk_umem(&xsk_info.umem, umem_buffer, NUM_FRAMES * FRAME_SIZE);
    if (ret) {
        goto cleanup;
    }
    
    ret = configure_xsk_socket(&xsk_info, interface, queue_id);
    if (ret) {
        goto cleanup;
    }
    
    xsk_socket__info = &xsk_info;
    
    // Run ML processor
    ret = run_ml_processor(&xsk_info, example_ml_processor, NULL);
    
    print_statistics(&xsk_info);
    
cleanup:
    if (xsk_info.xsk) {
        xsk_socket__delete(xsk_info.xsk);
    }
    if (xsk_info.umem.umem) {
        xsk_umem__delete(xsk_info.umem.umem);
    }
    if (umem_buffer != MAP_FAILED) {
        munmap(umem_buffer, NUM_FRAMES * FRAME_SIZE);
    }
    
    printf("AF_XDP ML processor shutdown complete\n");
    return ret;
} 
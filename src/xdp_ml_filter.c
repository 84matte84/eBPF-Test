#include <linux/bpf.h>
#include <bpf/bpf_helpers.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/udp.h>
#include <linux/tcp.h>
#include <linux/in.h>

// Enhanced feature structure for ML/AI
struct ml_feature {
    // Network layer
    __u32 src_ip;           // Source IP
    __u32 dst_ip;           // Destination IP
    __u16 src_port;         // Source port
    __u16 dst_port;         // Destination port
    __u8 protocol;          // IP protocol (TCP/UDP/ICMP)
    __u16 pkt_len;          // Total packet length
    
    // ML-specific features
    __u8 tcp_flags;         // TCP flags for behavior analysis
    __u16 payload_len;      // Payload size (for traffic analysis)
    __u64 flow_hash;        // Flow identifier
    __u64 timestamp;        // Processing timestamp
    
    // Derived features
    __u8 traffic_class;     // Traffic classification (0=normal, 1=suspicious, 2=priority)
    __u8 direction;         // 0=inbound, 1=outbound
} __attribute__((packed));

// BPF Maps
struct {
    __uint(type, BPF_MAP_TYPE_XSKMAP);
    __uint(max_entries, 64);  // Support for multiple queues
    __uint(key_size, sizeof(int));
    __uint(value_size, sizeof(int));
} xsks_map SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 16);
    __uint(key_size, sizeof(__u32));
    __uint(value_size, sizeof(__u64));
} stats_map SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 1);
    __uint(key_size, sizeof(__u32));
    __uint(value_size, sizeof(__u32));
} config_map SEC(".maps");

// Configuration structure
struct ml_config {
    __u32 sampling_rate;    // 1-in-N sampling (1=all packets, 100=every 100th)
    __u32 max_ml_rate;      // Maximum packets/sec to ML pipeline
    __u32 filter_mask;      // Protocol filter bitmask
    __u32 queue_id;         // AF_XDP queue ID
};

// Statistics indices
#define STAT_TOTAL_PACKETS     0
#define STAT_FILTERED_PACKETS  1
#define STAT_SAMPLED_PACKETS   2
#define STAT_ML_PACKETS        3
#define STAT_DROPPED_PACKETS   4
#define STAT_TCP_PACKETS       5
#define STAT_UDP_PACKETS       6
#define STAT_PROCESSING_TIME   7

// Flow classification for ML
#define FLOW_NORMAL     0
#define FLOW_SUSPICIOUS 1
#define FLOW_PRIORITY   2

static inline void update_stat(__u32 key, __u64 value) {
    __u64 *existing = bpf_map_lookup_elem(&stats_map, &key);
    if (existing) {
        __sync_fetch_and_add(existing, value);
    }
}

// Simple flow hashing for session tracking
static inline __u64 compute_flow_hash(__u32 src_ip, __u32 dst_ip, 
                                      __u16 src_port, __u16 dst_port, __u8 proto) {
    __u64 hash = 0;
    hash ^= src_ip;
    hash ^= (__u64)dst_ip << 32;
    hash ^= (__u64)src_port << 16;
    hash ^= (__u64)dst_port << 48;
    hash ^= (__u64)proto << 8;
    return hash;
}

// Traffic classification for ML
static inline __u8 classify_traffic(__u32 src_ip, __u32 dst_ip, 
                                   __u16 src_port, __u16 dst_port, __u8 proto) {
    // Simple heuristic classification (extend with ML model results)
    
    // Priority: SSH, DNS, HTTP/HTTPS
    if (src_port == 22 || dst_port == 22 ||      // SSH
        src_port == 53 || dst_port == 53 ||      // DNS
        src_port == 80 || dst_port == 80 ||      // HTTP
        src_port == 443 || dst_port == 443) {    // HTTPS
        return FLOW_PRIORITY;
    }
    
    // Suspicious: High ports, uncommon protocols
    if ((src_port > 49152 && dst_port > 49152) || 
        (proto != IPPROTO_TCP && proto != IPPROTO_UDP)) {
        return FLOW_SUSPICIOUS;
    }
    
    return FLOW_NORMAL;
}

// Packet sampling decision
static inline int should_sample(__u32 sampling_rate) {
    static __u32 counter = 0;
    counter++;
    return (counter % sampling_rate) == 0;
}

// Parse Ethernet header
static inline int parse_ethernet(void *data, void *data_end, void **next_hdr) {
    struct ethhdr *eth = data;
    
    if (data + sizeof(*eth) > data_end)
        return -1;
        
    if (eth->h_proto != __constant_htons(ETH_P_IP))
        return -1;
        
    *next_hdr = data + sizeof(*eth);
    return 0;
}

// Parse IP header and extract info
static inline int parse_ip(void *data, void *data_end, void **next_hdr,
                          __u32 *src_ip, __u32 *dst_ip, __u8 *proto, __u16 *total_len) {
    struct iphdr *ip = data;
    
    if (data + sizeof(*ip) > data_end)
        return -1;
        
    if (ip->version != 4)
        return -1;
        
    *src_ip = ip->saddr;
    *dst_ip = ip->daddr;
    *proto = ip->protocol;
    *total_len = __bpf_ntohs(ip->tot_len);
    
    *next_hdr = data + (ip->ihl * 4);
    return 0;
}

// Parse transport layer (TCP/UDP)
static inline int parse_transport(void *data, void *data_end, __u8 proto,
                                 __u16 *src_port, __u16 *dst_port, __u8 *tcp_flags) {
    if (proto == IPPROTO_TCP) {
        struct tcphdr *tcp = data;
        if (data + sizeof(*tcp) > data_end)
            return -1;
            
        *src_port = __bpf_ntohs(tcp->source);
        *dst_port = __bpf_ntohs(tcp->dest);
        *tcp_flags = ((unsigned char *)tcp)[13]; // TCP flags byte
        return 0;
        
    } else if (proto == IPPROTO_UDP) {
        struct udphdr *udp = data;
        if (data + sizeof(*udp) > data_end)
            return -1;
            
        *src_port = __bpf_ntohs(udp->source);
        *dst_port = __bpf_ntohs(udp->dest);
        *tcp_flags = 0;
        return 0;
    }
    
    return -1; // Unsupported protocol
}

SEC("xdp_ml_filter")
int xdp_ml_packet_processor(struct xdp_md *ctx) {
    void *data_end = (void *)(long)ctx->data_end;
    void *data = (void *)(long)ctx->data;
    void *next_hdr;
    
    __u64 start_time = bpf_ktime_get_ns();
    update_stat(STAT_TOTAL_PACKETS, 1);
    
    // Parse Ethernet
    if (parse_ethernet(data, data_end, &next_hdr) < 0) {
        update_stat(STAT_DROPPED_PACKETS, 1);
        return XDP_PASS;
    }
    
    // Parse IP
    __u32 src_ip, dst_ip;
    __u8 protocol;
    __u16 total_len;
    if (parse_ip(next_hdr, data_end, &next_hdr, &src_ip, &dst_ip, &protocol, &total_len) < 0) {
        update_stat(STAT_DROPPED_PACKETS, 1);
        return XDP_PASS;
    }
    
    // Parse transport layer
    __u16 src_port, dst_port;
    __u8 tcp_flags;
    if (parse_transport(next_hdr, data_end, protocol, &src_port, &dst_port, &tcp_flags) < 0) {
        update_stat(STAT_DROPPED_PACKETS, 1);
        return XDP_PASS;
    }
    
    // Update protocol-specific statistics
    if (protocol == IPPROTO_TCP) {
        update_stat(STAT_TCP_PACKETS, 1);
    } else if (protocol == IPPROTO_UDP) {
        update_stat(STAT_UDP_PACKETS, 1);
    }
    
    update_stat(STAT_FILTERED_PACKETS, 1);
    
    // Get configuration for sampling
    __u32 config_key = 0;
    struct ml_config *config = bpf_map_lookup_elem(&config_map, &config_key);
    __u32 sampling_rate = config ? config->sampling_rate : 100; // Default: 1 in 100
    
    // Sampling decision for ML pipeline
    if (!should_sample(sampling_rate)) {
        __u64 processing_time = bpf_ktime_get_ns() - start_time;
        update_stat(STAT_PROCESSING_TIME, processing_time);
        return XDP_PASS; // Keep processing but don't send to ML
    }
    
    update_stat(STAT_SAMPLED_PACKETS, 1);
    
    // Traffic classification
    __u8 traffic_class = classify_traffic(src_ip, dst_ip, src_port, dst_port, protocol);
    
    // For high-priority or suspicious traffic, send to AF_XDP for ML analysis
    if (traffic_class == FLOW_PRIORITY || traffic_class == FLOW_SUSPICIOUS) {
        update_stat(STAT_ML_PACKETS, 1);
        
        // Redirect to AF_XDP queue for ML processing
        __u32 queue_id = config ? config->queue_id : 0;
        int ret = bpf_redirect_map(&xsks_map, queue_id, 0);
        if (ret == XDP_REDIRECT) {
            __u64 processing_time = bpf_ktime_get_ns() - start_time;
            update_stat(STAT_PROCESSING_TIME, processing_time);
            return XDP_REDIRECT;
        }
    }
    
    __u64 processing_time = bpf_ktime_get_ns() - start_time;
    update_stat(STAT_PROCESSING_TIME, processing_time);
    return XDP_PASS;
}

char _license[] SEC("license") = "GPL"; 
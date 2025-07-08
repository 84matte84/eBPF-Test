#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/udp.h>
#include <linux/in.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>

// Feature structure - must match include/feature.h
struct feature {
    __u32 src_ip;      // Source IP address (network byte order)
    __u32 dst_ip;      // Destination IP address (network byte order)
    __u16 src_port;    // Source port (network byte order)
    __u16 dst_port;    // Destination port (network byte order)
    __u16 pkt_len;     // Total packet length
    __u64 timestamp;   // Processing timestamp (nanoseconds)
} __attribute__((packed));

// Ring buffer map for sending features to userspace
struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 256 * 1024); // 256KB ring buffer
} feature_rb SEC(".maps");

// Statistics map to track performance
struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 4);
    __type(key, __u32);
    __type(value, __u64);
} stats_map SEC(".maps");

// Statistics indices
#define STAT_PACKETS_TOTAL     0
#define STAT_PACKETS_UDP       1
#define STAT_PACKETS_DROPPED   2
#define STAT_PROCESSING_TIME   3

// Helper function to update statistics
static __always_inline void update_stat(__u32 index, __u64 value) {
    __u64 *stat = bpf_map_lookup_elem(&stats_map, &index);
    if (stat) {
        __sync_fetch_and_add(stat, value);
    }
}

// Parse Ethernet header
static __always_inline int parse_ethernet(void *data, void *data_end, void **next_header) {
    struct ethhdr *eth = data;
    
    // Bounds check
    if ((void *)(eth + 1) > data_end) {
        return -1;
    }
    
    // Check if it's IPv4
    if (eth->h_proto != bpf_htons(ETH_P_IP)) {
        return -1;
    }
    
    *next_header = (void *)(eth + 1);
    return 0;
}

// Parse IPv4 header
static __always_inline int parse_ipv4(void *data, void *data_end, void **next_header, 
                                       __u32 *src_ip, __u32 *dst_ip, __u16 *total_len) {
    struct iphdr *ip = data;
    
    // Bounds check for IP header
    if ((void *)(ip + 1) > data_end) {
        return -1;
    }
    
    // Verify IP version and header length
    if (ip->version != 4 || ip->ihl < 5) {
        return -1;
    }
    
    // Calculate IP header length
    int ip_header_len = ip->ihl * 4;
    
    // Bounds check for variable length IP header
    if (data + ip_header_len > data_end) {
        return -1;
    }
    
    // Check if it's UDP
    if (ip->protocol != IPPROTO_UDP) {
        return -1;
    }
    
    // Extract IP addresses and total length
    *src_ip = ip->saddr;
    *dst_ip = ip->daddr;
    *total_len = bpf_ntohs(ip->tot_len);
    
    *next_header = data + ip_header_len;
    return 0;
}

// Parse UDP header
static __always_inline int parse_udp(void *data, void *data_end, 
                                      __u16 *src_port, __u16 *dst_port) {
    struct udphdr *udp = data;
    
    // Bounds check
    if ((void *)(udp + 1) > data_end) {
        return -1;
    }
    
    *src_port = udp->source;
    *dst_port = udp->dest;
    
    return 0;
}

// Main XDP program
SEC("xdp")
int xdp_packet_processor(struct xdp_md *ctx) {
    void *data_end = (void *)(long)ctx->data_end;
    void *data = (void *)(long)ctx->data;
    void *next_header;
    
    __u64 start_time = bpf_ktime_get_ns();
    
    // Update total packet count
    update_stat(STAT_PACKETS_TOTAL, 1);
    
    // Parse Ethernet header
    if (parse_ethernet(data, data_end, &next_header) < 0) {
        update_stat(STAT_PACKETS_DROPPED, 1);
        return XDP_PASS; // Not IP, let kernel handle it
    }
    
    // Parse IPv4 header
    __u32 src_ip, dst_ip;
    __u16 total_len;
    if (parse_ipv4(next_header, data_end, &next_header, &src_ip, &dst_ip, &total_len) < 0) {
        update_stat(STAT_PACKETS_DROPPED, 1);
        return XDP_PASS; // Not UDP, let kernel handle it
    }
    
    // Parse UDP header
    __u16 src_port, dst_port;
    if (parse_udp(next_header, data_end, &src_port, &dst_port) < 0) {
        update_stat(STAT_PACKETS_DROPPED, 1);
        return XDP_PASS; // Malformed UDP
    }
    
    // Reserve space in ring buffer
    struct feature *feature = bpf_ringbuf_reserve(&feature_rb, sizeof(*feature), 0);
    if (!feature) {
        update_stat(STAT_PACKETS_DROPPED, 1);
        return XDP_PASS; // Ring buffer full
    }
    
    // Populate feature structure
    feature->src_ip = src_ip;
    feature->dst_ip = dst_ip;
    feature->src_port = src_port;
    feature->dst_port = dst_port;
    feature->pkt_len = total_len;
    feature->timestamp = start_time;
    
    // Submit to ring buffer
    bpf_ringbuf_submit(feature, 0);
    
    // Update statistics
    update_stat(STAT_PACKETS_UDP, 1);
    __u64 processing_time = bpf_ktime_get_ns() - start_time;
    update_stat(STAT_PROCESSING_TIME, processing_time);
    
    return XDP_PASS; // Let packet continue through network stack
}

char _license[] SEC("license") = "GPL"; 
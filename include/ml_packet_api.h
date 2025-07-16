#ifndef ML_PACKET_API_H
#define ML_PACKET_API_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

// ============================================================================
// ML PACKET PROCESSING API
// High-Performance XDP + AF_XDP packet analysis for AI/ML applications
// ============================================================================

// Feature structure for ML/AI analysis
typedef struct {
    // Network identifiers
    uint32_t src_ip;           // Source IP address
    uint32_t dst_ip;           // Destination IP address  
    uint16_t src_port;         // Source port
    uint16_t dst_port;         // Destination port
    uint8_t protocol;          // IP protocol (TCP=6, UDP=17)
    
    // Packet characteristics
    uint16_t pkt_len;          // Total packet length
    uint16_t payload_len;      // Payload size
    uint64_t timestamp;        // Processing timestamp (nanoseconds)
    
    // ML-specific features
    uint8_t tcp_flags;         // TCP flags (for behavior analysis)
    uint8_t packet_entropy;    // Payload entropy (0-255, encryption detection)
    uint64_t flow_hash;        // Flow identifier for session tracking
    uint8_t ttl;               // IP TTL (OS fingerprinting)
    uint16_t window_size;      // TCP window size (capacity detection)
    
    // Derived features
    uint8_t traffic_class;     // 0=normal, 1=suspicious, 2=priority
    uint8_t direction;         // 0=inbound, 1=outbound
    uint32_t inter_arrival_time; // Time since last packet in flow (microseconds)
} ml_packet_feature_t;

// Configuration for packet processing
typedef struct {
    // Sampling configuration
    uint32_t sampling_rate;    // 1-in-N sampling (1=all, 100=every 100th)
    uint32_t max_ml_rate;      // Maximum packets/sec to ML pipeline
    
    // Protocol filtering
    bool enable_tcp;           // Process TCP packets
    bool enable_udp;           // Process UDP packets
    bool enable_icmp;          // Process ICMP packets
    
    // Performance tuning
    uint32_t batch_size;       // Batch size for ML processing
    uint32_t buffer_size;      // Internal buffer size
    bool zero_copy_mode;       // Enable AF_XDP zero-copy
    
    // Network interface
    const char *interface;     // Network interface name
    uint32_t queue_id;         // XDP queue ID (for multi-queue)
} ml_packet_config_t;

// Performance statistics
typedef struct {
    // Packet counters
    uint64_t total_packets;         // Total packets seen by XDP
    uint64_t filtered_packets;      // Packets passing protocol filter
    uint64_t sampled_packets;       // Packets selected for ML analysis
    uint64_t ml_packets_processed;  // Packets sent to ML callback
    uint64_t dropped_packets;       // Packets dropped (buffer full, errors)
    
    // Protocol breakdown
    uint64_t tcp_packets;           // TCP packet count
    uint64_t udp_packets;           // UDP packet count
    uint64_t other_packets;         // Other protocol count
    
    // Performance metrics
    uint64_t total_bytes;           // Total bytes processed
    uint64_t processing_time_ns;    // Total ML processing time
    double avg_processing_time_us;  // Average ML processing time per packet
    double packets_per_second;      // Current processing rate
    double cpu_usage_percent;       // CPU usage percentage
} ml_packet_stats_t;

// Error codes
typedef enum {
    ML_PACKET_SUCCESS = 0,
    ML_PACKET_ERROR_INVALID_PARAM = -1,
    ML_PACKET_ERROR_INIT_FAILED = -2,
    ML_PACKET_ERROR_INTERFACE_NOT_FOUND = -3,
    ML_PACKET_ERROR_PERMISSION_DENIED = -4,
    ML_PACKET_ERROR_MEMORY_ALLOCATION = -5,
    ML_PACKET_ERROR_XDP_LOAD_FAILED = -6,
    ML_PACKET_ERROR_AF_XDP_FAILED = -7,
    ML_PACKET_ERROR_NOT_INITIALIZED = -8,
    ML_PACKET_ERROR_ALREADY_RUNNING = -9,
    ML_PACKET_ERROR_TIMEOUT = -10
} ml_packet_error_t;

// ML callback function type
// Returns: 0 for normal packet, non-zero for anomaly/action required
typedef int (*ml_packet_callback_t)(const ml_packet_feature_t *feature, void *user_context);

// Processing handle (opaque)
typedef struct ml_packet_processor ml_packet_processor_t;

// ============================================================================
// CORE API FUNCTIONS
// ============================================================================

/**
 * Initialize ML packet processor
 * @param config Processing configuration
 * @param callback ML processing callback function
 * @param user_context User data passed to callback
 * @return Processor handle or NULL on error
 */
ml_packet_processor_t* ml_packet_init(const ml_packet_config_t *config,
                                      ml_packet_callback_t callback,
                                      void *user_context);

/**
 * Start packet processing
 * @param processor Processor handle
 * @return ML_PACKET_SUCCESS or error code
 */
int ml_packet_start(ml_packet_processor_t *processor);

/**
 * Stop packet processing (blocks until complete)
 * @param processor Processor handle
 * @return ML_PACKET_SUCCESS or error code
 */
int ml_packet_stop(ml_packet_processor_t *processor);

/**
 * Get current performance statistics
 * @param processor Processor handle
 * @param stats Output statistics structure
 * @return ML_PACKET_SUCCESS or error code
 */
int ml_packet_get_stats(ml_packet_processor_t *processor, 
                        ml_packet_stats_t *stats);

/**
 * Update configuration (some parameters require restart)
 * @param processor Processor handle
 * @param config New configuration
 * @return ML_PACKET_SUCCESS or error code
 */
int ml_packet_update_config(ml_packet_processor_t *processor,
                           const ml_packet_config_t *config);

/**
 * Cleanup and destroy processor
 * @param processor Processor handle
 */
void ml_packet_destroy(ml_packet_processor_t *processor);

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

/**
 * Get default configuration
 * @param config Output configuration structure
 */
void ml_packet_get_default_config(ml_packet_config_t *config);

/**
 * Convert error code to human-readable string
 * @param error Error code
 * @return Error description string
 */
const char* ml_packet_error_string(ml_packet_error_t error);

/**
 * Convert IP address to string
 * @param ip IP address (host byte order)
 * @param buffer Output buffer (minimum 16 bytes)
 */
void ml_packet_ip_to_string(uint32_t ip, char *buffer);

/**
 * Calculate flow hash from packet features
 * @param feature Packet features
 * @return Flow hash for session tracking
 */
uint64_t ml_packet_calculate_flow_hash(const ml_packet_feature_t *feature);

/**
 * Check if current user has required permissions
 * @return true if permissions OK, false otherwise
 */
bool ml_packet_check_permissions(void);

/**
 * List available network interfaces
 * @param interfaces Output array of interface names
 * @param max_interfaces Maximum number of interfaces to return
 * @return Number of interfaces found, or -1 on error
 */
int ml_packet_list_interfaces(char **interfaces, int max_interfaces);

// ============================================================================
// ADVANCED FEATURES
// ============================================================================

/**
 * Set custom traffic classifier (replaces built-in heuristics)
 * @param processor Processor handle
 * @param classifier Custom classification function
 * @param context User context for classifier
 * @return ML_PACKET_SUCCESS or error code
 */
typedef uint8_t (*ml_traffic_classifier_t)(const ml_packet_feature_t *feature, void *context);
int ml_packet_set_classifier(ml_packet_processor_t *processor,
                             ml_traffic_classifier_t classifier,
                             void *context);

/**
 * Enable packet capture for debugging (saves raw packets)
 * @param processor Processor handle
 * @param filename Output pcap filename
 * @param max_packets Maximum packets to capture
 * @return ML_PACKET_SUCCESS or error code
 */
int ml_packet_enable_capture(ml_packet_processor_t *processor,
                            const char *filename,
                            uint32_t max_packets);

/**
 * Add flow tracking (maintains state per flow)
 * @param processor Processor handle
 * @param max_flows Maximum concurrent flows to track
 * @param timeout_seconds Flow timeout in seconds
 * @return ML_PACKET_SUCCESS or error code
 */
int ml_packet_enable_flow_tracking(ml_packet_processor_t *processor,
                                  uint32_t max_flows,
                                  uint32_t timeout_seconds);

// ============================================================================
// PERFORMANCE OPTIMIZATION HELPERS
// ============================================================================

/**
 * Optimize system for high-performance packet processing
 * @param interface Network interface to optimize
 * @return ML_PACKET_SUCCESS or error code
 */
int ml_packet_optimize_system(const char *interface);

/**
 * Get recommended configuration for target throughput
 * @param target_pps Target packets per second
 * @param config Output optimized configuration
 * @return ML_PACKET_SUCCESS or error code
 */
int ml_packet_get_optimized_config(uint32_t target_pps, 
                                  ml_packet_config_t *config);

/**
 * Benchmark system performance
 * @param interface Network interface to test
 * @param duration_seconds Test duration
 * @param max_pps Output maximum sustained PPS
 * @return ML_PACKET_SUCCESS or error code
 */
int ml_packet_benchmark(const char *interface, 
                       uint32_t duration_seconds,
                       uint32_t *max_pps);

// ============================================================================
// INTEGRATION EXAMPLES
// ============================================================================

/**
 * Example: Simple anomaly detection
 * Demonstrates basic API usage with built-in anomaly detection
 */
int ml_packet_example_anomaly_detection(const char *interface);

/**
 * Example: Real-time traffic analysis
 * Shows how to integrate with external ML frameworks
 */
int ml_packet_example_traffic_analysis(const char *interface);

/**
 * Example: Network security monitoring
 * Demonstrates flow tracking and threat detection
 */
int ml_packet_example_security_monitoring(const char *interface);

#ifdef __cplusplus
}
#endif

#endif // ML_PACKET_API_H 
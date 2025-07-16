#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <time.h>
#include <math.h>

#include "../include/ml_packet_api.h"

// ============================================================================
// ML/AI INTEGRATION EXAMPLE
// Demonstrates how to use the high-performance packet processing API
// for real-time network traffic analysis and anomaly detection
// ============================================================================

// Global state for demo
static volatile int running = 1;
static ml_packet_processor_t *processor = NULL;

// ML model state (simplified for demo)
typedef struct {
    // Statistical models
    double tcp_port_entropy[65536];     // Port usage entropy
    double packet_size_mean;            // Average packet size
    double packet_size_stddev;          // Packet size standard deviation
    uint64_t total_flows;               // Total flows seen
    
    // Anomaly detection thresholds
    double entropy_threshold;           // High entropy threshold
    double size_anomaly_factor;         // Packet size anomaly factor
    uint32_t suspicious_port_min;       // Suspicious port range
    
    // Real-time statistics
    uint64_t packets_analyzed;          // Total packets processed
    uint64_t anomalies_detected;        // Anomalies found
    uint64_t normal_traffic;            // Normal traffic count
    
    // Flow tracking
    uint64_t active_flows;              // Currently active flows
    uint64_t completed_flows;           // Completed flows
} ml_model_state_t;

// Initialize ML model
static void init_ml_model(ml_model_state_t *model) {
    memset(model, 0, sizeof(*model));
    
    // Initialize thresholds based on your ML training
    model->entropy_threshold = 200.0;      // High entropy packets
    model->size_anomaly_factor = 3.0;      // 3 standard deviations
    model->suspicious_port_min = 49152;    // High ports
    
    // Initialize statistical baselines
    model->packet_size_mean = 800.0;       // Typical packet size
    model->packet_size_stddev = 400.0;     // Size variance
    
    printf("[ML] Initialized anomaly detection model\n");
}

// Update ML model with new observations (online learning)
static void update_ml_model(ml_model_state_t *model, const ml_packet_feature_t *feature) {
    model->packets_analyzed++;
    
    // Update packet size statistics (running average)
    double alpha = 0.01; // Learning rate
    double size_diff = feature->pkt_len - model->packet_size_mean;
    model->packet_size_mean += alpha * size_diff;
    model->packet_size_stddev = (1.0 - alpha) * model->packet_size_stddev + 
                               alpha * fabs(size_diff);
    
    // Update port entropy (simplified)
    if (feature->src_port < 65536) {
        model->tcp_port_entropy[feature->src_port] += alpha;
    }
    if (feature->dst_port < 65536) {
        model->tcp_port_entropy[feature->dst_port] += alpha;
    }
}

// ML anomaly detection algorithm
static int detect_anomaly(ml_model_state_t *model, const ml_packet_feature_t *feature) {
    int anomaly_score = 0;
    char reasons[256] = "";
    
    // 1. Payload entropy analysis (encryption/compression detection)
    if (feature->packet_entropy > model->entropy_threshold) {
        anomaly_score += 3;
        strcat(reasons, "high-entropy ");
    }
    
    // 2. Packet size anomaly detection
    double size_z_score = fabs(feature->pkt_len - model->packet_size_mean) / 
                         model->packet_size_stddev;
    if (size_z_score > model->size_anomaly_factor) {
        anomaly_score += 2;
        strcat(reasons, "size-anomaly ");
    }
    
    // 3. Suspicious port analysis
    if ((feature->src_port > model->suspicious_port_min && 
         feature->dst_port > model->suspicious_port_min) ||
        (feature->src_port == feature->dst_port)) {
        anomaly_score += 2;
        strcat(reasons, "suspicious-ports ");
    }
    
    // 4. Protocol-specific analysis
    if (feature->protocol == 6) { // TCP
        // Unusual TCP flags combinations
        if (feature->tcp_flags & 0x3F && // Multiple flags
            !(feature->tcp_flags & 0x18)) { // But not standard ACK/PSH
            anomaly_score += 1;
            strcat(reasons, "tcp-flags ");
        }
        
        // Very small or very large TCP windows
        if (feature->window_size < 1024 || feature->window_size > 65000) {
            anomaly_score += 1;
            strcat(reasons, "tcp-window ");
        }
    }
    
    // 5. TTL-based OS fingerprinting anomalies
    if (feature->ttl < 32 || feature->ttl > 128) {
        anomaly_score += 1;
        strcat(reasons, "unusual-ttl ");
    }
    
    // 6. Flow-based analysis
    // Rapid successive packets from same flow (potential DDoS)
    if (feature->inter_arrival_time < 1000) { // Less than 1ms
        anomaly_score += 1;
        strcat(reasons, "rapid-flow ");
    }
    
    // Log significant anomalies
    if (anomaly_score >= 3) {
        char src_ip[16], dst_ip[16];
        ml_packet_ip_to_string(feature->src_ip, src_ip);
        ml_packet_ip_to_string(feature->dst_ip, dst_ip);
        
        printf("[ANOMALY] Score=%d, %s:%d->%s:%d, proto=%d, len=%d, entropy=%d, reasons=[%s]\n",
               anomaly_score, src_ip, feature->src_port, dst_ip, feature->dst_port,
               feature->protocol, feature->pkt_len, feature->packet_entropy, reasons);
        
        model->anomalies_detected++;
        return anomaly_score;
    }
    
    model->normal_traffic++;
    return 0;
}

// Advanced ML processor with multiple detection algorithms
static int advanced_ml_processor(const ml_packet_feature_t *feature, void *context) {
    ml_model_state_t *model = (ml_model_state_t *)context;
    
    // Update model with new observation
    update_ml_model(model, feature);
    
    // Run anomaly detection
    int anomaly_result = detect_anomaly(model, feature);
    
    // Periodic statistics reporting
    if (model->packets_analyzed % 10000 == 0) {
        printf("[ML] Processed %lu packets, detected %lu anomalies (%.2f%% anomaly rate)\n",
               model->packets_analyzed, model->anomalies_detected,
               (double)model->anomalies_detected / model->packets_analyzed * 100.0);
    }
    
    return anomaly_result;
}

// Network security monitoring example
static int security_monitoring_callback(const ml_packet_feature_t *feature, void *context) {
    static uint64_t packet_count = 0;
    static uint64_t last_report_time = 0;
    
    packet_count++;
    
    // Security-focused analysis
    int threat_level = 0;
    
    // Known attack patterns
    if (feature->protocol == 6) { // TCP
        // SYN flood detection
        if ((feature->tcp_flags & 0x02) && !(feature->tcp_flags & 0x10)) {
            threat_level = 2; // SYN without ACK
        }
        
        // Port scanning detection
        if (feature->dst_port == 22 || feature->dst_port == 80 || 
            feature->dst_port == 443 || feature->dst_port == 3389) {
            static uint32_t scan_ports[1000];
            static int scan_count = 0;
            
            // Simple scan detection (extend with bloom filters)
            scan_ports[scan_count % 1000] = feature->src_ip;
            scan_count++;
            
            if (scan_count > 100) { // Potential scanner
                threat_level = 1;
            }
        }
    }
    
    // DNS tunneling detection
    if (feature->protocol == 17 && (feature->src_port == 53 || feature->dst_port == 53)) {
        if (feature->pkt_len > 512) { // Large DNS packet
            threat_level = 1;
        }
    }
    
    // Report threats
    if (threat_level > 0) {
        char src_ip[16], dst_ip[16];
        ml_packet_ip_to_string(feature->src_ip, src_ip);
        ml_packet_ip_to_string(feature->dst_ip, dst_ip);
        
        printf("[THREAT] Level=%d, %s:%d->%s:%d, proto=%d\n",
               threat_level, src_ip, feature->src_port, dst_ip, feature->dst_port,
               feature->protocol);
    }
    
    // Periodic reporting
    uint64_t current_time = feature->timestamp / 1000000000; // Convert to seconds
    if (current_time - last_report_time >= 30) { // Every 30 seconds
        printf("[SECURITY] Monitored %lu packets in last 30s\n", packet_count);
        packet_count = 0;
        last_report_time = current_time;
    }
    
    return threat_level;
}

// Signal handler
void signal_handler(int sig) {
    printf("\nShutting down ML processor (signal %d)...\n", sig);
    running = 0;
}

// Print comprehensive statistics
static void print_final_stats(ml_packet_processor_t *proc, ml_model_state_t *model) {
    ml_packet_stats_t stats;
    
    if (ml_packet_get_stats(proc, &stats) == ML_PACKET_SUCCESS) {
        printf("\n=== FINAL PERFORMANCE STATISTICS ===\n");
        printf("Total packets processed: %lu\n", stats.total_packets);
        printf("ML packets analyzed: %lu\n", stats.ml_packets_processed);
        printf("Packets per second: %.2f\n", stats.packets_per_second);
        printf("Average processing time: %.2f µs\n", stats.avg_processing_time_us);
        printf("CPU usage: %.2f%%\n", stats.cpu_usage_percent);
        
        printf("\n=== ML MODEL STATISTICS ===\n");
        printf("Total packets analyzed: %lu\n", model->packets_analyzed);
        printf("Anomalies detected: %lu\n", model->anomalies_detected);
        printf("Normal traffic: %lu\n", model->normal_traffic);
        printf("Anomaly rate: %.4f%%\n", 
               (double)model->anomalies_detected / model->packets_analyzed * 100.0);
        
        printf("\n=== PROTOCOL BREAKDOWN ===\n");
        printf("TCP packets: %lu\n", stats.tcp_packets);
        printf("UDP packets: %lu\n", stats.udp_packets);
        printf("Other packets: %lu\n", stats.other_packets);
        
        // Performance assessment
        if (stats.packets_per_second > 10000) {
            printf("\n✅ HIGH PERFORMANCE: Processing > 10k PPS\n");
        } else if (stats.packets_per_second > 1000) {
            printf("\n⚠️  MEDIUM PERFORMANCE: Processing > 1k PPS\n");
        } else {
            printf("\n❌ LOW PERFORMANCE: Processing < 1k PPS\n");
        }
        
        if (stats.avg_processing_time_us < 10.0) {
            printf("✅ LOW LATENCY: < 10µs per packet\n");
        } else if (stats.avg_processing_time_us < 100.0) {
            printf("⚠️  MEDIUM LATENCY: < 100µs per packet\n");
        } else {
            printf("❌ HIGH LATENCY: > 100µs per packet\n");
        }
    }
}

// Main demonstration function
int main(int argc, char **argv) {
    const char *interface = "eth0";
    int demo_mode = 1; // 1=anomaly, 2=security
    
    if (argc > 1) {
        interface = argv[1];
    }
    if (argc > 2) {
        demo_mode = atoi(argv[2]);
    }
    
    printf("=== HIGH-PERFORMANCE ML PACKET PROCESSING DEMO ===\n");
    printf("Interface: %s\n", interface);
    printf("Demo mode: %s\n", demo_mode == 1 ? "Anomaly Detection" : "Security Monitoring");
    
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    
    // Check permissions
    if (!ml_packet_check_permissions()) {
        fprintf(stderr, "Error: Root permissions required for XDP\n");
        return 1;
    }
    
    // Get optimized configuration
    ml_packet_config_t config;
    ml_packet_get_default_config(&config);
    
    // Optimize for high throughput
    config.interface = interface;
    config.sampling_rate = 10;           // Process every 10th packet
    config.max_ml_rate = 50000;          // Up to 50k PPS to ML
    config.enable_tcp = true;
    config.enable_udp = true;
    config.enable_icmp = false;
    config.zero_copy_mode = true;        // Enable AF_XDP zero-copy
    config.batch_size = 64;              // Process in batches
    config.buffer_size = 4096 * 1024;    // 4MB buffer
    
    printf("Configuration: sampling=1:%d, max_rate=%d PPS, zero_copy=%s\n",
           config.sampling_rate, config.max_ml_rate, 
           config.zero_copy_mode ? "enabled" : "disabled");
    
    // Initialize ML model
    ml_model_state_t ml_model;
    init_ml_model(&ml_model);
    
    // Choose processing callback
    ml_packet_callback_t callback = (demo_mode == 1) ? 
        advanced_ml_processor : security_monitoring_callback;
    void *context = (demo_mode == 1) ? &ml_model : NULL;
    
    // Initialize processor
    processor = ml_packet_init(&config, callback, context);
    if (!processor) {
        fprintf(stderr, "Failed to initialize ML packet processor\n");
        return 1;
    }
    
    printf("✅ ML packet processor initialized successfully\n");
    
    // Optimize system performance
    printf("Optimizing system for high-performance processing...\n");
    if (ml_packet_optimize_system(interface) != ML_PACKET_SUCCESS) {
        printf("⚠️  Warning: System optimization failed (may impact performance)\n");
    } else {
        printf("✅ System optimized for maximum performance\n");
    }
    
    // Start processing
    if (ml_packet_start(processor) != ML_PACKET_SUCCESS) {
        fprintf(stderr, "Failed to start packet processing\n");
        ml_packet_destroy(processor);
        return 1;
    }
    
    printf("🚀 Started ML packet processing - press Ctrl+C to stop\n");
    printf("Monitoring traffic for ML/AI analysis...\n\n");
    
    // Main processing loop
    while (running) {
        sleep(5);
        
        // Get current statistics
        ml_packet_stats_t stats;
        if (ml_packet_get_stats(processor, &stats) == ML_PACKET_SUCCESS) {
            printf("[STATUS] PPS: %.0f, Processed: %lu, ML: %lu, CPU: %.1f%%, Latency: %.1fµs\n",
                   stats.packets_per_second, stats.total_packets, 
                   stats.ml_packets_processed, stats.cpu_usage_percent,
                   stats.avg_processing_time_us);
        }
    }
    
    // Cleanup
    printf("\nStopping packet processing...\n");
    ml_packet_stop(processor);
    
    print_final_stats(processor, &ml_model);
    
    ml_packet_destroy(processor);
    
    printf("✅ ML packet processor shutdown complete\n");
    return 0;
}

// ============================================================================
// INTEGRATION EXAMPLES FOR SPECIFIC ML FRAMEWORKS
// ============================================================================

#ifdef TENSORFLOW_INTEGRATION
#include <tensorflow/c/c_api.h>

// TensorFlow integration example
static int tensorflow_ml_processor(const ml_packet_feature_t *feature, void *context) {
    TF_Session *session = (TF_Session *)context;
    
    // Convert packet features to TensorFlow input tensor
    float input_data[16] = {
        (float)feature->src_ip / UINT32_MAX,
        (float)feature->dst_ip / UINT32_MAX,
        (float)feature->src_port / 65535.0f,
        (float)feature->dst_port / 65535.0f,
        (float)feature->protocol / 255.0f,
        (float)feature->pkt_len / 1500.0f,
        (float)feature->payload_len / 1400.0f,
        (float)feature->packet_entropy / 255.0f,
        (float)feature->tcp_flags / 255.0f,
        (float)feature->ttl / 255.0f,
        (float)feature->window_size / 65535.0f,
        (float)feature->traffic_class / 2.0f,
        (float)feature->direction,
        (float)feature->inter_arrival_time / 1000000.0f,
        0.0f, 0.0f // Padding
    };
    
    // Run TensorFlow inference
    // ... TF_SessionRun implementation ...
    
    return 0; // Return prediction result
}
#endif

#ifdef PYTORCH_INTEGRATION
// PyTorch C++ integration example
static int pytorch_ml_processor(const ml_packet_feature_t *feature, void *context) {
    // Convert to PyTorch tensor and run inference
    // torch::Tensor input = torch::from_blob(features, {1, 16});
    // torch::Tensor output = model.forward(input);
    
    return 0;
}
#endif 
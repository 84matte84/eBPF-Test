#!/usr/bin/env python3
"""
Configuration Validation Module for eBPF-Test Two-Machine Testing

Provides comprehensive validation for YAML configuration files with detailed
error reporting and type checking.

Author: eBPF-Test Project
License: MIT
"""

import ipaddress
import logging
import sys
from typing import Dict, Any, List, Optional, Union, Set
from dataclasses import dataclass
from pathlib import Path


class ValidationError(Exception):
    """Exception raised when configuration validation fails."""
    pass


@dataclass
class ValidationResult:
    """Result of configuration validation."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    
    def add_error(self, error: str) -> None:
        """Add an error message."""
        self.errors.append(error)
        self.is_valid = False
    
    def add_warning(self, warning: str) -> None:
        """Add a warning message."""
        self.warnings.append(warning)
    
    def __bool__(self) -> bool:
        """Return True if validation passed."""
        return self.is_valid


class ConfigValidator:
    """Comprehensive configuration validator."""
    
    def __init__(self) -> None:
        self.logger = logging.getLogger(f"{__name__}.ConfigValidator")
        
        # Define valid configuration sections
        self.required_sections = {
            'test_config', 
            'traffic_config', 
            'network_config',
            'monitoring_config',
            'results_config'
        }
        
        self.optional_sections = {
            'xdp_config',
            'performance_targets',
            'qa_config',
            'logging_config',
            'debug_config',
            'machine_roles',
            'security_config',
            'presets'
        }
        
        # Define valid traffic patterns
        self.valid_traffic_patterns = {'constant', 'burst', 'ramp', 'random'}
        
        # Define valid log levels
        self.valid_log_levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
        
        # Define valid output formats
        self.valid_output_formats = {'json', 'csv', 'markdown', 'yaml'}
    
    def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate complete configuration."""
        result = ValidationResult(is_valid=True, errors=[], warnings=[])
        
        try:
            # Check top-level structure
            self._validate_top_level_structure(config, result)
            
            # Validate individual sections
            if 'test_config' in config:
                self._validate_test_config(config['test_config'], result)
            
            if 'traffic_config' in config:
                self._validate_traffic_config(config['traffic_config'], result)
            
            if 'network_config' in config:
                self._validate_network_config(config['network_config'], result)
            
            if 'monitoring_config' in config:
                self._validate_monitoring_config(config['monitoring_config'], result)
            
            if 'results_config' in config:
                self._validate_results_config(config['results_config'], result)
            
            if 'xdp_config' in config:
                self._validate_xdp_config(config['xdp_config'], result)
            
            if 'performance_targets' in config:
                self._validate_performance_targets(config['performance_targets'], result)
            
            if 'logging_config' in config:
                self._validate_logging_config(config['logging_config'], result)
            
            if 'presets' in config:
                self._validate_presets(config['presets'], result)
            
            # Cross-section validation
            self._validate_cross_section_consistency(config, result)
            
        except Exception as e:
            result.add_error(f"Validation failed with exception: {e}")
        
        return result
    
    def _validate_top_level_structure(self, config: Dict[str, Any], result: ValidationResult) -> None:
        """Validate top-level configuration structure."""
        if not isinstance(config, dict):
            result.add_error("Configuration must be a dictionary")
            return
        
        # Check for required sections
        for section in self.required_sections:
            if section not in config:
                result.add_error(f"Missing required section: {section}")
        
        # Check for unknown sections
        known_sections = self.required_sections | self.optional_sections
        for section in config.keys():
            if section not in known_sections:
                result.add_warning(f"Unknown configuration section: {section}")
    
    def _validate_test_config(self, test_config: Dict[str, Any], result: ValidationResult) -> None:
        """Validate test configuration section."""
        required_fields = {'duration'}
        optional_fields = {'name', 'description', 'warmup_time', 'cooldown_time'}
        
        self._check_required_fields(test_config, required_fields, 'test_config', result)
        self._check_unknown_fields(test_config, required_fields | optional_fields, 'test_config', result)
        
        # Validate field types and ranges
        if 'duration' in test_config:
            if not isinstance(test_config['duration'], (int, float)) or test_config['duration'] <= 0:
                result.add_error("test_config.duration must be a positive number")
            elif test_config['duration'] > 3600:
                result.add_warning("test_config.duration is very long (>1 hour)")
        
        if 'warmup_time' in test_config:
            if not isinstance(test_config['warmup_time'], (int, float)) or test_config['warmup_time'] < 0:
                result.add_error("test_config.warmup_time must be a non-negative number")
        
        if 'cooldown_time' in test_config:
            if not isinstance(test_config['cooldown_time'], (int, float)) or test_config['cooldown_time'] < 0:
                result.add_error("test_config.cooldown_time must be a non-negative number")
    
    def _validate_traffic_config(self, traffic_config: Dict[str, Any], result: ValidationResult) -> None:
        """Validate traffic configuration section."""
        required_fields = {'packet_rate', 'packet_size', 'flows', 'threads'}
        optional_fields = {'patterns'}
        
        self._check_required_fields(traffic_config, required_fields, 'traffic_config', result)
        self._check_unknown_fields(traffic_config, required_fields | optional_fields, 'traffic_config', result)
        
        # Validate packet rate
        if 'packet_rate' in traffic_config:
            rate = traffic_config['packet_rate']
            if not isinstance(rate, int) or rate <= 0:
                result.add_error("traffic_config.packet_rate must be a positive integer")
            elif rate > 1_000_000:
                result.add_warning("traffic_config.packet_rate is very high (>1M pps)")
        
        # Validate packet size
        if 'packet_size' in traffic_config:
            size = traffic_config['packet_size']
            if not isinstance(size, int) or size <= 0:
                result.add_error("traffic_config.packet_size must be a positive integer")
            elif size < 64:
                result.add_warning("traffic_config.packet_size is very small (<64 bytes)")
            elif size > 9000:
                result.add_error("traffic_config.packet_size exceeds jumbo frame size (9000 bytes)")
        
        # Validate flows
        if 'flows' in traffic_config:
            flows = traffic_config['flows']
            if not isinstance(flows, int) or flows <= 0:
                result.add_error("traffic_config.flows must be a positive integer")
            elif flows > 1000:
                result.add_warning("traffic_config.flows is very high (>1000)")
        
        # Validate threads
        if 'threads' in traffic_config:
            threads = traffic_config['threads']
            if not isinstance(threads, int) or threads <= 0:
                result.add_error("traffic_config.threads must be a positive integer")
            elif threads > 64:
                result.add_warning("traffic_config.threads is very high (>64)")
        
        # Validate traffic patterns
        if 'patterns' in traffic_config:
            self._validate_traffic_patterns(traffic_config['patterns'], result)
    
    def _validate_traffic_patterns(self, patterns: Any, result: ValidationResult) -> None:
        """Validate traffic patterns configuration."""
        if not isinstance(patterns, list):
            result.add_error("traffic_config.patterns must be a list")
            return
        
        for i, pattern in enumerate(patterns):
            if not isinstance(pattern, dict):
                result.add_error(f"traffic_config.patterns[{i}] must be a dictionary")
                continue
            
            # Check required fields
            if 'name' not in pattern:
                result.add_error(f"traffic_config.patterns[{i}] missing required field 'name'")
            if 'type' not in pattern:
                result.add_error(f"traffic_config.patterns[{i}] missing required field 'type'")
            
            # Validate pattern type
            if 'type' in pattern and pattern['type'] not in self.valid_traffic_patterns:
                result.add_error(f"traffic_config.patterns[{i}].type '{pattern['type']}' is not valid. "
                               f"Valid types: {', '.join(self.valid_traffic_patterns)}")
    
    def _validate_network_config(self, network_config: Dict[str, Any], result: ValidationResult) -> None:
        """Validate network configuration section."""
        required_fields = {'src_machine', 'dst_machine', 'traffic_ports'}
        optional_fields = {'discovery'}
        
        self._check_required_fields(network_config, required_fields, 'network_config', result)
        self._check_unknown_fields(network_config, required_fields | optional_fields, 'network_config', result)
        
        # Validate machine configurations
        if 'src_machine' in network_config:
            self._validate_machine_config(network_config['src_machine'], 'network_config.src_machine', result)
        
        if 'dst_machine' in network_config:
            self._validate_machine_config(network_config['dst_machine'], 'network_config.dst_machine', result)
        
        # Validate traffic ports
        if 'traffic_ports' in network_config:
            ports = network_config['traffic_ports']
            if not isinstance(ports, list):
                result.add_error("network_config.traffic_ports must be a list")
            elif not ports:
                result.add_error("network_config.traffic_ports cannot be empty")
            else:
                for i, port in enumerate(ports):
                    if not isinstance(port, int) or port < 1 or port > 65535:
                        result.add_error(f"network_config.traffic_ports[{i}] must be a valid port number (1-65535)")
    
    def _validate_machine_config(self, machine_config: Dict[str, Any], prefix: str, result: ValidationResult) -> None:
        """Validate machine configuration."""
        required_fields = {'ip', 'control_port'}
        optional_fields = {'hostname', 'interface'}
        
        self._check_required_fields(machine_config, required_fields, prefix, result)
        self._check_unknown_fields(machine_config, required_fields | optional_fields, prefix, result)
        
        # Validate IP address
        if 'ip' in machine_config:
            try:
                ipaddress.ip_address(machine_config['ip'])
            except ValueError:
                result.add_error(f"{prefix}.ip is not a valid IP address")
        
        # Validate control port
        if 'control_port' in machine_config:
            port = machine_config['control_port']
            if not isinstance(port, int) or port < 1 or port > 65535:
                result.add_error(f"{prefix}.control_port must be a valid port number (1-65535)")
            elif port < 1024:
                result.add_warning(f"{prefix}.control_port is a privileged port (<1024)")
    
    def _validate_monitoring_config(self, monitoring_config: Dict[str, Any], result: ValidationResult) -> None:
        """Validate monitoring configuration section."""
        optional_fields = {'sample_rate', 'metrics', 'real_time'}
        
        self._check_unknown_fields(monitoring_config, optional_fields, 'monitoring_config', result)
        
        # Validate sample rate
        if 'sample_rate' in monitoring_config:
            rate = monitoring_config['sample_rate']
            if not isinstance(rate, (int, float)) or rate <= 0:
                result.add_error("monitoring_config.sample_rate must be a positive number")
            elif rate < 0.1:
                result.add_warning("monitoring_config.sample_rate is very fast (<0.1s)")
        
        # Validate metrics list
        if 'metrics' in monitoring_config:
            metrics = monitoring_config['metrics']
            if not isinstance(metrics, list):
                result.add_error("monitoring_config.metrics must be a list")
            else:
                valid_metrics = {'cpu_usage', 'memory_usage', 'network_stats', 'xdp_stats'}
                for metric in metrics:
                    if metric not in valid_metrics:
                        result.add_warning(f"monitoring_config.metrics contains unknown metric: {metric}")
    
    def _validate_results_config(self, results_config: Dict[str, Any], result: ValidationResult) -> None:
        """Validate results configuration section."""
        required_fields = {'output_dir'}
        optional_fields = {'filename_pattern', 'formats', 'include_raw_data', 'baseline_comparison'}
        
        self._check_required_fields(results_config, required_fields, 'results_config', result)
        self._check_unknown_fields(results_config, required_fields | optional_fields, 'results_config', result)
        
        # Validate output directory
        if 'output_dir' in results_config:
            output_dir = results_config['output_dir']
            if not isinstance(output_dir, str):
                result.add_error("results_config.output_dir must be a string")
            else:
                # Try to create directory path to check if it's valid
                try:
                    Path(output_dir).resolve()
                except (OSError, ValueError) as e:
                    result.add_error(f"results_config.output_dir is not a valid path: {e}")
        
        # Validate output formats
        if 'formats' in results_config:
            formats = results_config['formats']
            if not isinstance(formats, list):
                result.add_error("results_config.formats must be a list")
            else:
                for fmt in formats:
                    if fmt not in self.valid_output_formats:
                        result.add_error(f"results_config.formats contains invalid format: {fmt}. "
                                       f"Valid formats: {', '.join(self.valid_output_formats)}")
    
    def _validate_xdp_config(self, xdp_config: Dict[str, Any], result: ValidationResult) -> None:
        """Validate XDP configuration section."""
        optional_fields = {'program_path', 'mode', 'ring_buffer', 'stats'}
        
        self._check_unknown_fields(xdp_config, optional_fields, 'xdp_config', result)
        
        # Validate XDP mode
        if 'mode' in xdp_config:
            mode = xdp_config['mode']
            valid_modes = {'native', 'skb', 'hw'}
            if mode not in valid_modes:
                result.add_error(f"xdp_config.mode '{mode}' is not valid. "
                               f"Valid modes: {', '.join(valid_modes)}")
        
        # Validate program path
        if 'program_path' in xdp_config:
            path = xdp_config['program_path']
            if not isinstance(path, str):
                result.add_error("xdp_config.program_path must be a string")
    
    def _validate_performance_targets(self, targets: Dict[str, Any], result: ValidationResult) -> None:
        """Validate performance targets section."""
        optional_fields = {
            'min_throughput_pps', 
            'max_cpu_usage_percent', 
            'max_memory_usage_mb',
            'expected_cpu_efficiency_improvement',
            'expected_latency_reduction_percent'
        }
        
        self._check_unknown_fields(targets, optional_fields, 'performance_targets', result)
        
        # Validate numeric targets
        for field, value in targets.items():
            if field in optional_fields:
                if not isinstance(value, (int, float)) or value < 0:
                    result.add_error(f"performance_targets.{field} must be a non-negative number")
    
    def _validate_logging_config(self, logging_config: Dict[str, Any], result: ValidationResult) -> None:
        """Validate logging configuration section."""
        optional_fields = {'level', 'file_logging', 'console_logging', 'format'}
        
        self._check_unknown_fields(logging_config, optional_fields, 'logging_config', result)
        
        # Validate log level
        if 'level' in logging_config:
            level = logging_config['level']
            if level not in self.valid_log_levels:
                result.add_error(f"logging_config.level '{level}' is not valid. "
                               f"Valid levels: {', '.join(self.valid_log_levels)}")
    
    def _validate_presets(self, presets: Dict[str, Any], result: ValidationResult) -> None:
        """Validate presets configuration section."""
        if not isinstance(presets, dict):
            result.add_error("presets must be a dictionary")
            return
        
        for preset_name, preset_config in presets.items():
            if not isinstance(preset_config, dict):
                result.add_error(f"presets.{preset_name} must be a dictionary")
                continue
            
            # Validate that preset contains valid configuration sections
            for section in preset_config.keys():
                if section not in (self.required_sections | self.optional_sections):
                    result.add_warning(f"presets.{preset_name}.{section} is not a known configuration section")
    
    def _validate_cross_section_consistency(self, config: Dict[str, Any], result: ValidationResult) -> None:
        """Validate consistency across configuration sections."""
        
        # Check thread count vs flow count consistency
        if ('traffic_config' in config and 
            'threads' in config['traffic_config'] and 
            'flows' in config['traffic_config']):
            
            threads = config['traffic_config']['threads']
            flows = config['traffic_config']['flows']
            
            if threads > flows:
                result.add_warning(f"More threads ({threads}) than flows ({flows}) may reduce efficiency")
        
        # Check if traffic ports match flow count
        if ('traffic_config' in config and 
            'network_config' in config and
            'flows' in config['traffic_config'] and
            'traffic_ports' in config['network_config']):
            
            flows = config['traffic_config']['flows']
            ports = len(config['network_config']['traffic_ports'])
            
            if flows > ports:
                result.add_warning(f"More flows ({flows}) than traffic ports ({ports}) will cause port reuse")
        
        # Check IP address consistency
        if 'network_config' in config:
            src_ip = config['network_config'].get('src_machine', {}).get('ip')
            dst_ip = config['network_config'].get('dst_machine', {}).get('ip')
            
            if src_ip and dst_ip:
                if src_ip == dst_ip:
                    result.add_error("Source and destination IP addresses cannot be the same")
                
                # Check if they're in same subnet (basic check)
                try:
                    src_net = ipaddress.ip_network(f"{src_ip}/24", strict=False)
                    dst_addr = ipaddress.ip_address(dst_ip)
                    
                    if dst_addr not in src_net:
                        result.add_warning("Source and destination appear to be in different subnets")
                        
                except ValueError:
                    pass  # IP validation already done elsewhere
    
    def _check_required_fields(self, config: Dict[str, Any], required: Set[str], 
                             section: str, result: ValidationResult) -> None:
        """Check for required fields in a configuration section."""
        for field in required:
            if field not in config:
                result.add_error(f"{section} missing required field: {field}")
    
    def _check_unknown_fields(self, config: Dict[str, Any], known: Set[str], 
                            section: str, result: ValidationResult) -> None:
        """Check for unknown fields in a configuration section."""
        for field in config.keys():
            if field not in known:
                result.add_warning(f"{section} contains unknown field: {field}")


def validate_config_file(config_path: str) -> ValidationResult:
    """Validate a configuration file."""
    import yaml
    
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        validator = ConfigValidator()
        return validator.validate_config(config)
        
    except FileNotFoundError:
        result = ValidationResult(is_valid=False, errors=[], warnings=[])
        result.add_error(f"Configuration file not found: {config_path}")
        return result
    except yaml.YAMLError as e:
        result = ValidationResult(is_valid=False, errors=[], warnings=[])
        result.add_error(f"YAML parsing error: {e}")
        return result
    except Exception as e:
        result = ValidationResult(is_valid=False, errors=[], warnings=[])
        result.add_error(f"Validation error: {e}")
        return result


def main() -> int:
    """Command-line interface for configuration validation."""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description='Validate eBPF-Test configuration files')
    parser.add_argument('config_file', help='Path to configuration file')
    parser.add_argument('--strict', action='store_true', help='Treat warnings as errors')
    parser.add_argument('--quiet', action='store_true', help='Only show errors')
    
    args = parser.parse_args()
    
    result = validate_config_file(args.config_file)
    
    if not args.quiet:
        print(f"Validating configuration file: {args.config_file}")
        print()
    
    # Print errors
    if result.errors:
        print("❌ ERRORS:")
        for error in result.errors:
            print(f"  • {error}")
        print()
    
    # Print warnings
    if result.warnings and not args.quiet:
        print("⚠️  WARNINGS:")
        for warning in result.warnings:
            print(f"  • {warning}")
        print()
    
    # Print result
    if result.is_valid and (not result.warnings or not args.strict):
        if not args.quiet:
            print("✅ Configuration is valid!")
        return 0
    else:
        if result.warnings and args.strict:
            print("❌ Configuration has warnings (treating as errors due to --strict)")
        else:
            print("❌ Configuration is invalid!")
        return 1


if __name__ == '__main__':
    sys.exit(main()) 
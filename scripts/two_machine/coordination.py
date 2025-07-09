#!/usr/bin/env python3
"""
Machine-to-Machine Coordination Module for eBPF-Test Two-Machine Testing

Provides REST API-based communication between src_machine and dst_machine
for synchronized test execution and results collection.

Author: eBPF-Test Project
License: MIT
"""

import json
import time
import logging
import threading
import requests
from typing import Dict, Any, Optional, Callable, Union, List, Protocol
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import socket
import platform
from dataclasses import dataclass
import traceback


# Custom Exception Classes
class CoordinationError(Exception):
    """Base exception for coordination-related errors."""
    pass


class NetworkError(CoordinationError):
    """Network-related coordination errors."""
    pass


class ValidationError(CoordinationError):
    """Input validation errors."""
    pass


class APIError(CoordinationError):
    """API-related errors."""
    pass


# Protocol for coordination handlers
class CoordinationHandlerProtocol(Protocol):
    """Protocol defining the interface for coordination handlers."""
    
    def get_status(self) -> Dict[str, Any]: ...
    def get_config(self) -> Dict[str, Any]: ...
    def update_config(self, config: Dict[str, Any]) -> bool: ...
    def start_test(self, test_params: Dict[str, Any]) -> bool: ...
    def stop_test(self, stop_params: Dict[str, Any]) -> Dict[str, Any]: ...
    def get_results(self) -> Dict[str, Any]: ...
    def get_metrics(self) -> Dict[str, Any]: ...


@dataclass(frozen=True)
class APIEndpoints:
    """REST API endpoints for machine coordination."""
    
    health: str = '/health'
    status: str = '/status'
    config: str = '/config'
    start_test: str = '/start_test'
    stop_test: str = '/stop_test'
    results: str = '/results'
    metrics: str = '/metrics'


@dataclass
class HealthInfo:
    """Health check information."""
    status: str
    timestamp: float
    hostname: str
    platform: str
    python_version: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'status': self.status,
            'timestamp': self.timestamp,
            'machine_info': {
                'hostname': self.hostname,
                'platform': self.platform,
                'python_version': self.python_version
            }
        }


class InputValidator:
    """Input validation utilities."""
    
    @staticmethod
    def validate_test_params(params: Dict[str, Any]) -> None:
        """Validate test parameters."""
        if not isinstance(params, dict):
            raise ValidationError("Test parameters must be a dictionary")
        
        # Check for required fields
        required_fields = ['duration', 'packet_rate']
        for field in required_fields:
            if field not in params:
                raise ValidationError(f"Missing required field: {field}")
        
        # Validate data types and ranges
        if not isinstance(params['duration'], (int, float)) or params['duration'] <= 0:
            raise ValidationError("Duration must be a positive number")
        
        if not isinstance(params['packet_rate'], (int, float)) or params['packet_rate'] <= 0:
            raise ValidationError("Packet rate must be a positive number")
    
    @staticmethod
    def validate_config(config: Dict[str, Any]) -> None:
        """Validate configuration data."""
        if not isinstance(config, dict):
            raise ValidationError("Configuration must be a dictionary")
        
        # Add specific validation rules as needed
        # This can be expanded based on your configuration schema


class CoordinationServer:
    """HTTP server for handling coordination requests."""
    
    def __init__(
        self, 
        host: str = '0.0.0.0', 
        port: int = 8080, 
        coordination_handler: Optional[CoordinationHandlerProtocol] = None
    ) -> None:
        self.host = host
        self.port = port
        self.coordination_handler = coordination_handler
        self.server: Optional[HTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.running = False
        self.endpoints = APIEndpoints()
        
        # Setup logging
        self.logger = logging.getLogger(f"{__name__}.CoordinationServer")
        
    def start(self) -> None:
        """Start the coordination server."""
        if self.running:
            self.logger.warning("Server is already running")
            return
        
        try:
            # Create request handler class with access to coordination handler
            handler_class = type(
                'CoordinationRequestHandler', 
                (CoordinationRequestHandler,), 
                {
                    'coordination_handler': self.coordination_handler,
                    'endpoints': self.endpoints,
                    'logger': self.logger
                }
            )
            
            self.server = HTTPServer((self.host, self.port), handler_class)
            self.server_thread = threading.Thread(
                target=self.server.serve_forever,
                name=f"CoordinationServer-{self.host}:{self.port}"
            )
            self.server_thread.daemon = True
            self.server_thread.start()
            self.running = True
            
            self.logger.info(f"Coordination server started on {self.host}:{self.port}")
            
        except OSError as e:
            error_msg = f"Failed to bind to {self.host}:{self.port}: {e}"
            self.logger.error(error_msg)
            raise NetworkError(error_msg)
        except Exception as e:
            error_msg = f"Server startup failed: {e}"
            self.logger.error(error_msg)
            raise CoordinationError(error_msg)
    
    def stop(self) -> None:
        """Stop the coordination server."""
        if not self.running:
            self.logger.warning("Server is not running")
            return
        
        try:
            if self.server:
                self.server.shutdown()
                self.server.server_close()
                
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=5.0)
                
            self.running = False
            self.logger.info("Coordination server stopped")
            
        except Exception as e:
            self.logger.error(f"Error stopping server: {e}")
            raise CoordinationError(f"Server shutdown failed: {e}")
    
    def is_running(self) -> bool:
        """Check if server is running."""
        return self.running


class CoordinationRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for coordination API."""
    
    # These will be set by the server when creating the handler class
    coordination_handler: Optional[CoordinationHandlerProtocol] = None
    endpoints: APIEndpoints = APIEndpoints()
    logger: Optional[logging.Logger] = None
    
    def log_message(self, format: str, *args) -> None:
        """Override to use proper logging."""
        if self.logger:
            self.logger.debug(format % args)
    
    def do_GET(self) -> None:
        """Handle GET requests."""
        try:
            path = urlparse(self.path).path
            query_params = parse_qs(urlparse(self.path).query)
            
            if path == self.endpoints.health:
                self._handle_health_check()
            elif path == self.endpoints.status:
                self._handle_status_request()
            elif path == self.endpoints.config:
                self._handle_config_request()
            elif path == self.endpoints.results:
                self._handle_results_request()
            elif path == self.endpoints.metrics:
                self._handle_metrics_request()
            else:
                self._send_error(404, f"Endpoint not found: {path}")
                
        except Exception as e:
            self._log_error("GET request failed", e)
            self._send_error(500, f"Server error: {e}")
    
    def do_POST(self) -> None:
        """Handle POST requests."""
        try:
            path = urlparse(self.path).path
            content_length = int(self.headers.get('Content-Length', 0))
            
            if content_length > 1_000_000:  # 1MB limit
                self._send_error(413, "Request entity too large")
                return
            
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8')) if post_data else {}
            except json.JSONDecodeError as e:
                self._send_error(400, f"Invalid JSON data: {e}")
                return
            except UnicodeDecodeError as e:
                self._send_error(400, f"Invalid UTF-8 encoding: {e}")
                return
            
            if path == self.endpoints.config:
                self._handle_config_update(data)
            elif path == self.endpoints.start_test:
                self._handle_start_test(data)
            elif path == self.endpoints.stop_test:
                self._handle_stop_test(data)
            else:
                self._send_error(404, f"Endpoint not found: {path}")
                
        except Exception as e:
            self._log_error("POST request failed", e)
            self._send_error(500, f"Server error: {e}")
    
    def _handle_health_check(self) -> None:
        """Handle health check requests."""
        try:
            health_info = HealthInfo(
                status='healthy',
                timestamp=time.time(),
                hostname=socket.gethostname(),
                platform=platform.platform(),
                python_version=platform.python_version()
            )
            self._send_json_response(health_info.to_dict())
        except Exception as e:
            self._log_error("Health check failed", e)
            self._send_error(500, f"Health check failed: {e}")
    
    def _handle_status_request(self) -> None:
        """Handle status requests."""
        if not self.coordination_handler:
            self._send_error(503, "Coordination handler not available")
            return
        
        try:
            status = self.coordination_handler.get_status()
            self._send_json_response(status)
        except Exception as e:
            self._log_error("Status request failed", e)
            self._send_error(500, f"Status request failed: {e}")
    
    def _handle_config_request(self) -> None:
        """Handle configuration requests."""
        if not self.coordination_handler:
            self._send_error(503, "Coordination handler not available")
            return
        
        try:
            config = self.coordination_handler.get_config()
            self._send_json_response(config)
        except Exception as e:
            self._log_error("Config request failed", e)
            self._send_error(500, f"Config request failed: {e}")
    
    def _handle_config_update(self, data: Dict[str, Any]) -> None:
        """Handle configuration updates."""
        if not self.coordination_handler:
            self._send_error(503, "Coordination handler not available")
            return
        
        try:
            InputValidator.validate_config(data)
            success = self.coordination_handler.update_config(data)
            
            if success:
                self._send_json_response({'status': 'config updated'})
            else:
                self._send_error(400, "Configuration update failed")
                
        except ValidationError as e:
            self._send_error(400, f"Validation error: {e}")
        except Exception as e:
            self._log_error("Config update failed", e)
            self._send_error(500, f"Config update failed: {e}")
    
    def _handle_start_test(self, data: Dict[str, Any]) -> None:
        """Handle test start requests."""
        if not self.coordination_handler:
            self._send_error(503, "Coordination handler not available")
            return
        
        try:
            InputValidator.validate_test_params(data)
            success = self.coordination_handler.start_test(data)
            
            if success:
                self._send_json_response({'status': 'test started'})
            else:
                self._send_error(400, "Failed to start test")
                
        except ValidationError as e:
            self._send_error(400, f"Validation error: {e}")
        except Exception as e:
            self._log_error("Start test failed", e)
            self._send_error(500, f"Start test failed: {e}")
    
    def _handle_stop_test(self, data: Dict[str, Any]) -> None:
        """Handle test stop requests."""
        if not self.coordination_handler:
            self._send_error(503, "Coordination handler not available")
            return
        
        try:
            results = self.coordination_handler.stop_test(data)
            self._send_json_response({'status': 'test stopped', 'results': results})
        except Exception as e:
            self._log_error("Stop test failed", e)
            self._send_error(500, f"Stop test failed: {e}")
    
    def _handle_results_request(self) -> None:
        """Handle results requests."""
        if not self.coordination_handler:
            self._send_error(503, "Coordination handler not available")
            return
        
        try:
            results = self.coordination_handler.get_results()
            self._send_json_response(results)
        except Exception as e:
            self._log_error("Results request failed", e)
            self._send_error(500, f"Results request failed: {e}")
    
    def _handle_metrics_request(self) -> None:
        """Handle metrics requests."""
        if not self.coordination_handler:
            self._send_error(503, "Coordination handler not available")
            return
        
        try:
            metrics = self.coordination_handler.get_metrics()
            self._send_json_response(metrics)
        except Exception as e:
            self._log_error("Metrics request failed", e)
            self._send_error(500, f"Metrics request failed: {e}")
    
    def _send_json_response(self, data: Dict[str, Any], status_code: int = 200) -> None:
        """Send JSON response."""
        try:
            response_data = json.dumps(data, indent=2)
            
            self.send_response(status_code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response_data)))
            self.end_headers()
            self.wfile.write(response_data.encode('utf-8'))
            
        except Exception as e:
            self._log_error("Failed to send JSON response", e)
            self._send_error(500, "Failed to serialize response")
    
    def _send_error(self, status_code: int, message: str) -> None:
        """Send error response."""
        try:
            error_data = {
                'error': message,
                'status_code': status_code,
                'timestamp': time.time()
            }
            response_data = json.dumps(error_data, indent=2)
            
            self.send_response(status_code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response_data)))
            self.end_headers()
            self.wfile.write(response_data.encode('utf-8'))
            
        except Exception as e:
            # Fallback to basic HTTP error
            self.send_error(status_code, message)
    
    def _log_error(self, message: str, exception: Exception) -> None:
        """Log error with traceback."""
        if self.logger:
            self.logger.error(f"{message}: {exception}")
            self.logger.debug(f"Traceback: {traceback.format_exc()}")


class CoordinationClient:
    """HTTP client for coordination requests."""
    
    def __init__(
        self, 
        remote_host: str, 
        remote_port: int = 8080, 
        timeout: int = 30
    ) -> None:
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.timeout = timeout
        self.base_url = f"http://{remote_host}:{remote_port}"
        self.endpoints = APIEndpoints()
        self.session = requests.Session()
        
        # Setup logging
        self.logger = logging.getLogger(f"{__name__}.CoordinationClient")
        
        # Configure session
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'eBPF-Test-Coordination-Client/1.0'
        })
    
    def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make HTTP request with error handling."""
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method.upper() == 'GET':
                response = self.session.get(url, timeout=self.timeout)
            elif method.upper() == 'POST':
                json_data = json.dumps(data) if data else None
                response = self.session.post(url, data=json_data, timeout=self.timeout)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            
            try:
                return response.json()
            except json.JSONDecodeError as e:
                raise APIError(f"Invalid JSON response: {e}")
            
        except requests.exceptions.ConnectionError as e:
            raise NetworkError(f"Connection failed to {url}: {e}")
        except requests.exceptions.Timeout as e:
            raise NetworkError(f"Request timeout to {url}: {e}")
        except requests.exceptions.HTTPError as e:
            raise APIError(f"HTTP error {response.status_code}: {e}")
        except Exception as e:
            raise CoordinationError(f"Request failed: {e}")
    
    def check_health(self) -> Dict[str, Any]:
        """Check remote machine health."""
        return self._make_request('GET', self.endpoints.health)
    
    def get_status(self) -> Dict[str, Any]:
        """Get remote machine status."""
        return self._make_request('GET', self.endpoints.status)
    
    def get_config(self) -> Dict[str, Any]:
        """Get remote machine configuration."""
        return self._make_request('GET', self.endpoints.config)
    
    def update_config(self, config: Dict[str, Any]) -> bool:
        """Update remote machine configuration."""
        try:
            InputValidator.validate_config(config)
            response = self._make_request('POST', self.endpoints.config, config)
            return response.get('status') == 'config updated'
        except ValidationError as e:
            self.logger.error(f"Configuration validation failed: {e}")
            return False
    
    def start_test(self, test_params: Dict[str, Any]) -> bool:
        """Start test on remote machine."""
        try:
            InputValidator.validate_test_params(test_params)
            response = self._make_request('POST', self.endpoints.start_test, test_params)
            return response.get('status') == 'test started'
        except ValidationError as e:
            self.logger.error(f"Test parameters validation failed: {e}")
            return False
    
    def stop_test(self) -> Dict[str, Any]:
        """Stop test on remote machine."""
        return self._make_request('POST', self.endpoints.stop_test, {})
    
    def get_results(self) -> Dict[str, Any]:
        """Get test results from remote machine."""
        return self._make_request('GET', self.endpoints.results)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get metrics from remote machine."""
        return self._make_request('GET', self.endpoints.metrics)
    
    def wait_for_ready(self, max_wait_time: int = 60) -> bool:
        """Wait for remote machine to be ready."""
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            try:
                health = self.check_health()
                if health.get('status') == 'healthy':
                    self.logger.info(f"Remote machine {self.remote_host} is ready")
                    return True
            except (NetworkError, APIError) as e:
                self.logger.debug(f"Waiting for remote machine: {e}")
            
            time.sleep(2)
        
        self.logger.error(f"Remote machine {self.remote_host} not ready after {max_wait_time}s")
        return False
    
    def close(self) -> None:
        """Close the client session."""
        if self.session:
            self.session.close()


class CoordinationHandler:
    """Base class for coordination handlers."""
    
    def __init__(self) -> None:
        self.logger = logging.getLogger(f"{__name__}.CoordinationHandler")
        self.status = "idle"
        self.config: Dict[str, Any] = {}
        self.results: Dict[str, Any] = {}
        self.metrics: Dict[str, Any] = {}
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status."""
        return {
            'status': self.status,
            'timestamp': time.time(),
            'machine_type': self.__class__.__name__
        }
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration."""
        return self.config.copy()
    
    def update_config(self, config: Dict[str, Any]) -> bool:
        """Update configuration."""
        try:
            self.config.update(config)
            self.logger.info("Configuration updated")
            return True
        except Exception as e:
            self.logger.error(f"Configuration update failed: {e}")
            return False
    
    def start_test(self, test_params: Dict[str, Any]) -> bool:
        """Start test with given parameters. Override in subclasses."""
        self.logger.warning("start_test not implemented")
        return False
    
    def stop_test(self, stop_params: Dict[str, Any]) -> Dict[str, Any]:
        """Stop test and return results. Override in subclasses."""
        self.logger.warning("stop_test not implemented")
        return {}
    
    def get_results(self) -> Dict[str, Any]:
        """Get test results."""
        return self.results.copy()
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get performance metrics."""
        return self.metrics.copy()


def setup_coordination_logging(log_level: str = "INFO") -> None:
    """Setup logging for coordination module."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('coordination.log')
        ]
    )


if __name__ == "__main__":
    # Example usage
    setup_coordination_logging("DEBUG")
    
    # Test the coordination components
    handler = CoordinationHandler()
    
    # Start server
    server = CoordinationServer(coordination_handler=handler)
    server.start()
    
    try:
        # Test client
        client = CoordinationClient("localhost")
        
        if client.wait_for_ready(10):
            print("Server is ready!")
            
            # Test health check
            health = client.check_health()
            print(f"Health: {health}")
            
            # Test status
            status = client.get_status()
            print(f"Status: {status}")
            
        client.close()
        
    finally:
        server.stop()
        print("Test completed") 
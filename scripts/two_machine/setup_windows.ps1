# eBPF-Test Two-Machine Setup Script for Windows
# Sets up the Windows source machine for eBPF-Test two-machine testing

param(
    [switch]$CheckOnly,
    [switch]$Verbose
)

# Enable verbose output if requested
if ($Verbose) {
    $VerbosePreference = "Continue"
}

# Color functions for output
function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Blue
}

function Write-Success {
    param([string]$Message)
    Write-Host "[SUCCESS] $Message" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "[WARNING] $Message" -ForegroundColor Yellow
}

function Write-Error-Custom {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

# Banner
Write-Host "🚀 eBPF-Test Two-Machine Setup (Windows)" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
if (-not $isAdmin) {
    Write-Warning "Running without administrator privileges. Some features may not work properly."
    Write-Info "Consider running PowerShell as Administrator for full functionality."
}

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

Write-Info "Script directory: $ScriptDir"
Write-Info "Project root: $ProjectRoot"

# Check Python installation
Write-Info "=== Checking Python Installation ==="

try {
    $pythonVersion = python --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Python found: $pythonVersion"
        
        # Check if Python version is >= 3.8
        $versionMatch = $pythonVersion -match "Python (\d+)\.(\d+)"
        if ($versionMatch) {
            $majorVersion = [int]$matches[1]
            $minorVersion = [int]$matches[2]
            
            if ($majorVersion -gt 3 -or ($majorVersion -eq 3 -and $minorVersion -ge 8)) {
                Write-Success "Python version is sufficient (>=3.8)"
            } else {
                Write-Error-Custom "Python 3.8+ required, found Python $majorVersion.$minorVersion"
                Write-Info "Please install Python 3.8 or later from https://python.org"
                exit 1
            }
        }
    } else {
        Write-Error-Custom "Python not found in PATH"
        Write-Info "Please install Python 3.8+ from https://python.org"
        exit 1
    }
} catch {
    Write-Error-Custom "Failed to check Python version: $_"
    exit 1
}

# Check pip installation
Write-Info "Checking pip installation..."
try {
    $pipVersion = pip --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Success "pip found: $pipVersion"
    } else {
        Write-Error-Custom "pip not found"
        Write-Info "Please ensure pip is installed and in PATH"
        exit 1
    }
} catch {
    Write-Error-Custom "Failed to check pip: $_"
    exit 1
}

# Function to check if Python package is installed
function Test-PythonPackage {
    param([string]$PackageName)
    
    try {
        python -c "import $PackageName" 2>$null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

# Install Python dependencies
Write-Info "=== Installing Python Dependencies ==="

$requiredPackages = @("yaml", "requests", "psutil")
$missingPackages = @()

foreach ($package in $requiredPackages) {
    if (Test-PythonPackage $package) {
        Write-Success "Package '$package' is already installed"
    } else {
        $missingPackages += $package
    }
}

if ($missingPackages.Count -gt 0) {
    Write-Warning "Missing Python packages: $($missingPackages -join ', ')"
    
    if (-not $CheckOnly) {
        Write-Info "Installing missing packages..."
        
        foreach ($package in $missingPackages) {
            $packageName = $package
            if ($package -eq "yaml") {
                $packageName = "pyyaml"
            }
            
            Write-Info "Installing $packageName..."
            try {
                pip install $packageName
                if ($LASTEXITCODE -eq 0) {
                    Write-Success "Successfully installed $packageName"
                } else {
                    Write-Error-Custom "Failed to install $packageName"
                }
            } catch {
                Write-Error-Custom "Exception installing $packageName`: $_"
            }
        }
    }
} else {
    Write-Success "All required Python packages are installed"
}

# Create necessary directories
Write-Info "=== Creating Directory Structure ==="

$resultsDir = Join-Path $ProjectRoot "results\two_machine"
if (-not (Test-Path $resultsDir)) {
    try {
        New-Item -ItemType Directory -Path $resultsDir -Force | Out-Null
        Write-Success "Created results directory: $resultsDir"
    } catch {
        Write-Warning "Cannot create results directory: $_"
        Write-Info "Results will be created at runtime"
    }
} else {
    Write-Success "Results directory already exists"
}

# Network interface detection
Write-Info "=== Network Interface Detection ==="

try {
    # Get network adapters
    $adapters = Get-NetAdapter | Where-Object { $_.Status -eq "Up" -and $_.InterfaceDescription -notlike "*Loopback*" }
    
    if ($adapters.Count -gt 0) {
        Write-Success "Active network interfaces found:"
        foreach ($adapter in $adapters) {
            $ipAddress = (Get-NetIPAddress -InterfaceIndex $adapter.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress
            if ($ipAddress) {
                Write-Host "  - $($adapter.Name): $ipAddress ($($adapter.InterfaceDescription))" -ForegroundColor White
            } else {
                Write-Host "  - $($adapter.Name): No IPv4 address ($($adapter.InterfaceDescription))" -ForegroundColor Gray
            }
        }
        
        # Get default IP address
        try {
            $defaultIP = (Test-NetConnection -ComputerName "8.8.8.8" -Port 53 -InformationLevel Quiet -WarningAction SilentlyContinue)
            if ($defaultIP) {
                $localIP = (Get-NetRoute -DestinationPrefix "0.0.0.0/0" | Get-NetIPAddress -AddressFamily IPv4).IPAddress | Select-Object -First 1
                Write-Info "Detected default IP address: $localIP"
            }
        } catch {
            Write-Verbose "Could not detect default IP: $_"
        }
    } else {
        Write-Warning "No active network interfaces found"
    }
} catch {
    Write-Warning "Failed to detect network interfaces: $_"
}

# Check Windows Firewall
Write-Info "=== Windows Firewall Check ==="

try {
    $firewallProfile = Get-NetFirewallProfile -Profile Domain, Public, Private
    $enabledProfiles = $firewallProfile | Where-Object { $_.Enabled -eq $true }
    
    if ($enabledProfiles.Count -gt 0) {
        Write-Warning "Windows Firewall is enabled on $($enabledProfiles.Count) profile(s)"
        Write-Info "You may need to create firewall rules for:"
        Write-Info "  - Port 8080 (coordination)"
        Write-Info "  - Ports 12345-12348 (test traffic)"
        Write-Info ""
        Write-Info "Example PowerShell commands (run as Administrator):"
        Write-Info "New-NetFirewallRule -DisplayName 'eBPF-Test Coordination' -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow"
        Write-Info "New-NetFirewallRule -DisplayName 'eBPF-Test Traffic' -Direction Outbound -Protocol UDP -LocalPort 12345-12348 -Action Allow"
    } else {
        Write-Info "Windows Firewall is disabled"
    }
} catch {
    Write-Warning "Could not check Windows Firewall status: $_"
}

# Configuration validation
Write-Info "=== Configuration Validation ==="

$configFile = Join-Path $ScriptDir "config.yaml"
if (Test-Path $configFile) {
    Write-Success "Configuration file found: config.yaml"
    Write-Warning "Please update the following in config.yaml:"
    Write-Info "  - src_machine IP (network_config.src_machine.ip)"
    Write-Info "  - dst_machine IP (network_config.dst_machine.ip)"
} else {
    Write-Error-Custom "Configuration file not found: config.yaml"
    Write-Info "Please ensure config.yaml exists in the same directory as this script"
}

# Performance recommendations
Write-Info "=== Performance Recommendations ==="

# Check available memory
$memory = Get-WmiObject -Class Win32_ComputerSystem
$memoryGB = [math]::Round($memory.TotalPhysicalMemory / 1GB, 2)
Write-Info "Total system memory: $memoryGB GB"

if ($memoryGB -ge 8) {
    Write-Success "Sufficient memory for high-rate testing"
} elseif ($memoryGB -ge 4) {
    Write-Warning "Limited memory. Consider reducing packet rates for testing"
} else {
    Write-Warning "Low memory. Recommend testing with low packet rates only"
}

# Check CPU cores
$cpu = Get-WmiObject -Class Win32_Processor
$coreCount = ($cpu | Measure-Object -Property NumberOfCores -Sum).Sum
Write-Info "CPU cores: $coreCount"

if ($coreCount -ge 4) {
    Write-Success "Sufficient CPU cores for multi-threaded traffic generation"
} else {
    Write-Warning "Limited CPU cores. Consider reducing thread count"
}

# Check if check-only mode
if ($CheckOnly) {
    Write-Info "=== Check-Only Mode ==="
    Write-Success "System check completed"
    exit 0
}

# Next steps
Write-Info "=== Next Steps ==="
Write-Host ""
Write-Info "1. Update config.yaml with correct IP addresses:"
Write-Info "   - Set src_machine IP to your Windows machine's IP"
Write-Info "   - Set dst_machine IP to your Linux machine's IP"
Write-Host ""
Write-Info "2. Configure Windows Firewall (if enabled):"
Write-Info "   - Allow inbound TCP on port 8080 (coordination)"
Write-Info "   - Allow outbound UDP on ports 12345-12348 (traffic)"
Write-Host ""
Write-Info "3. Test configuration:"
Write-Info "   python src_machine.py --config config.yaml --check-only"
Write-Host ""
Write-Info "4. Run traffic generator:"
Write-Info "   python src_machine.py --config config.yaml --no-coordination"
Write-Host ""

Write-Success "Windows setup complete!"
Write-Info "See README.md for detailed usage instructions" 
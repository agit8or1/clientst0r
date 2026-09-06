"""
Phase 32 (v3.17.556) — the PowerShell script handed to the technician.

Built as a template with the server URL and token substituted at generation.
What it deliberately does *not* do is as important as what it does: no
credentials, no authentication attempts, no vulnerability probing, no writes to
anything on the network. It pings, reads the machine's own ARP table, optionally
asks DNS for a name, and optionally checks whether a handful of well-known ports
accept a TCP connection so a device can be loosely classified.

That last one is the only thing that touches a port at all, it is opt-in, and it
opens and immediately closes a connection — the same thing any client does before
saying hello.
"""
from __future__ import annotations

SCRIPT_VERSION = '1.0'

# Ports probed only when -Classify is passed. Each is here because what answers
# on it says something about what kind of device this is, and for no other
# reason.
CLASSIFY_PORTS = [80, 443, 22, 3389, 445, 9100]

_TEMPLATE = r'''<#
    Client St0r — Remote Network Discovery
    Script version {script_version}
    Generated {generated_at} for {org_name} / {location_name}

    RUN THIS ONLY ON A NETWORK YOU ARE AUTHORISED TO SCAN.

    What it does:
      * works out which IPv4 subnets this machine is on
      * pings each address in them
      * reads this machine's own ARP table for MAC addresses
      * optionally asks DNS for hostnames (-ResolveNames)
      * optionally checks whether a few well-known ports accept a connection,
        purely to guess a device type (-Classify)
      * writes a JSON summary locally, then uploads it

    What it does NOT do, by design:
      * no credentials, and no attempt to authenticate to anything
      * no vulnerability or exploit scanning
      * no writes or changes to any device on the network
      * nothing is installed, and nothing is left running when it exits

    The token below is single-use and expires at {expires_at}. It can only add
    device records to this one location and cannot read anything back.
#>

[CmdletBinding()]
param(
    [string]   $ServerUrl     = '{server_url}',
    [string]   $Token         = '{token}',
    [string[]] $Subnet,
    [int]      $TimeoutMs     = 300,
    [int]      $MaxHosts      = 1024,
    [switch]   $ResolveNames,
    [switch]   $Classify,
    [switch]   $DryRun,
    [switch]   $SkipUpload,
    [string]   $OutputJsonPath = "$env:TEMP\clientst0r-discovery.json"
)

$ErrorActionPreference = 'Stop'
$ScriptVersion = '{script_version}'

Write-Host ''
Write-Host '  Client St0r — Network Discovery' -ForegroundColor Cyan
Write-Host '  Run this only on networks you are authorised to scan.' -ForegroundColor Yellow
Write-Host "  Results upload to: $ServerUrl" -ForegroundColor Gray
Write-Host ''

function Get-LocalSubnets {{
    # Active IPv4 adapters with a normal prefix length. /31 and /32 are
    # point-to-point or loopback and have nothing to sweep.
    $found = @()
    try {{
        $addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {{
                $_.IPAddress -notlike '127.*' -and
                $_.IPAddress -notlike '169.254.*' -and
                $_.PrefixLength -ge 16 -and $_.PrefixLength -le 30
            }}
        foreach ($a in $addresses) {{
            $found += "$($a.IPAddress)/$($a.PrefixLength)"
        }}
    }} catch {{
        # PowerShell 5.1 on older builds, or no NetTCPIP module.
        $legacy = Get-WmiObject Win32_NetworkAdapterConfiguration |
            Where-Object {{ $_.IPEnabled -and $_.IPAddress }}
        foreach ($cfg in $legacy) {{
            for ($i = 0; $i -lt $cfg.IPAddress.Count; $i++) {{
                $ip = $cfg.IPAddress[$i]
                if ($ip -match '^\d+\.\d+\.\d+\.\d+$' -and $ip -notlike '127.*') {{
                    $found += "$ip/24"
                }}
            }}
        }}
    }}
    return $found | Select-Object -Unique
}}

function Expand-Subnet {{
    param([string] $Cidr, [int] $Limit)

    $parts  = $Cidr.Split('/')
    $ipParts = $parts[0].Split('.')
    $prefix  = [int]$parts[1]

    $ipInt = ([uint32]$ipParts[0] -shl 24) -bor ([uint32]$ipParts[1] -shl 16) -bor `
             ([uint32]$ipParts[2] -shl 8)  -bor  [uint32]$ipParts[3]
    $mask  = [uint32]([math]::Pow(2, 32) - [math]::Pow(2, 32 - $prefix))
    $network   = $ipInt -band $mask
    $broadcast = $network -bor (-bnot $mask -band [uint32]4294967295)

    $addresses = @()
    for ($current = $network + 1; $current -lt $broadcast; $current++) {{
        if ($addresses.Count -ge $Limit) {{ break }}
        $addresses += ('{{0}}.{{1}}.{{2}}.{{3}}' -f `
            (($current -shr 24) -band 255), (($current -shr 16) -band 255),
            (($current -shr 8) -band 255),  ($current -band 255))
    }}
    return $addresses
}}

function Get-ArpTable {{
    $table = @{{}}
    try {{
        foreach ($n in (Get-NetNeighbor -AddressFamily IPv4 -ErrorAction Stop |
                        Where-Object {{ $_.State -ne 'Unreachable' }})) {{
            if ($n.LinkLayerAddress -and $n.LinkLayerAddress -ne '00-00-00-00-00-00') {{
                $table[$n.IPAddress] = $n.LinkLayerAddress
            }}
        }}
    }} catch {{
        foreach ($line in (arp -a)) {{
            if ($line -match '(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{{17}})') {{
                $table[$matches[1]] = $matches[2]
            }}
        }}
    }}
    return $table
}}

function Test-Port {{
    param([string] $ComputerName, [int] $Port, [int] $Timeout)
    $client = New-Object System.Net.Sockets.TcpClient
    try {{
        $async = $client.BeginConnect($ComputerName, $Port, $null, $null)
        if ($async.AsyncWaitHandle.WaitOne($Timeout, $false) -and $client.Connected) {{
            $client.EndConnect($async) | Out-Null
            return $true
        }}
        return $false
    }} catch {{
        return $false
    }} finally {{
        # Opened and closed. Nothing is sent.
        $client.Close()
    }}
}}

function Get-DeviceType {{
    param([int[]] $OpenPorts)
    if ($OpenPorts -contains 9100) {{ return 'printer' }}
    if ($OpenPorts -contains 3389) {{ return 'workstation' }}
    if ($OpenPorts -contains 445)  {{ return 'server' }}
    if ($OpenPorts -contains 22)   {{ return 'server' }}
    if (($OpenPorts -contains 80) -or ($OpenPorts -contains 443)) {{ return 'router' }}
    return ''
}}

# --- sweep ------------------------------------------------------------------

$targets = @()
$subnets = if ($Subnet) {{ $Subnet }} else {{ Get-LocalSubnets }}

if (-not $subnets -or $subnets.Count -eq 0) {{
    Write-Host '  No active IPv4 subnet found. Pass -Subnet 192.168.1.0/24 to set one.' -ForegroundColor Red
    exit 1
}}

Write-Host "  Subnets: $($subnets -join ', ')" -ForegroundColor Gray
foreach ($cidr in $subnets) {{
    $targets += Expand-Subnet -Cidr $cidr -Limit $MaxHosts
}}
$targets = $targets | Select-Object -Unique
Write-Host "  Sweeping $($targets.Count) address(es)…" -ForegroundColor Gray

$alive = @()
$done  = 0
foreach ($ip in $targets) {{
    $done++
    if ($done % 64 -eq 0) {{
        Write-Progress -Activity 'Network discovery' -Status "$done / $($targets.Count)" `
            -PercentComplete (($done / $targets.Count) * 100)
    }}
    $ping = New-Object System.Net.NetworkInformation.Ping
    try {{
        if ($ping.Send($ip, $TimeoutMs).Status -eq 'Success') {{ $alive += $ip }}
    }} catch {{ }}
}}
Write-Progress -Activity 'Network discovery' -Completed

# The ARP table is read after the sweep, so pinging has populated it.
$arp = Get-ArpTable
foreach ($ip in $arp.Keys) {{
    if ($alive -notcontains $ip) {{ $alive += $ip }}
}}

Write-Host "  $($alive.Count) device(s) responded." -ForegroundColor Green

$devices = @()
foreach ($ip in $alive) {{
    $hostname = ''
    if ($ResolveNames) {{
        try {{ $hostname = [System.Net.Dns]::GetHostEntry($ip).HostName }} catch {{ }}
    }}

    $openPorts = @()
    $deviceType = ''
    if ($Classify) {{
        foreach ($port in @({classify_ports})) {{
            if (Test-Port -ComputerName $ip -Port $port -Timeout $TimeoutMs) {{
                $openPorts += $port
            }}
        }}
        $deviceType = Get-DeviceType -OpenPorts $openPorts
    }}

    $devices += [pscustomobject]@{{
        ip          = $ip
        mac         = if ($arp.ContainsKey($ip)) {{ $arp[$ip] }} else {{ '' }}
        hostname    = $hostname
        vendor      = ''
        device_type = $deviceType
        method      = 'icmp+arp'
        open_ports  = $openPorts
    }}
}}

$payload = [pscustomobject]@{{
    token            = $Token
    script_version   = $ScriptVersion
    scanner_hostname = $env:COMPUTERNAME
    subnets          = $subnets
    dry_run          = [bool]$DryRun
    devices          = $devices
}}

# Written before the upload, always. A failed upload must not lose the sweep.
$json = $payload | ConvertTo-Json -Depth 6
Set-Content -Path $OutputJsonPath -Value $json -Encoding UTF8
Write-Host "  Wrote $OutputJsonPath" -ForegroundColor Gray

if ($SkipUpload) {{
    Write-Host '  -SkipUpload set; nothing was sent.' -ForegroundColor Yellow
    exit 0
}}

Write-Host "  Uploading to $ServerUrl …" -ForegroundColor Gray
try {{
    $response = Invoke-RestMethod -Uri $ServerUrl -Method Post -Body $json `
        -ContentType 'application/json' -TimeoutSec 120
    if ($response.ok) {{
        Write-Host ("  Done: {{0}} device(s) — {{1}} created, {{2}} updated, {{3}} skipped, {{4}} error(s)." -f `
            $response.devices, $response.created, $response.updated,
            $response.skipped, $response.errors) -ForegroundColor Green
        if ($response.dry_run) {{
            Write-Host '  Dry run — nothing was written to the asset register.' -ForegroundColor Yellow
        }}
    }} else {{
        Write-Host "  Upload rejected: $($response.error)" -ForegroundColor Red
    }}
}} catch {{
    Write-Host "  Upload failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  The results are still in $OutputJsonPath." -ForegroundColor Yellow
    exit 1
}}
'''


def render_discovery_script(request, *, organization, location,
                            token_plaintext, expires_at):
    """The script, with this server's upload URL and the token baked in."""
    from django.urls import reverse
    from django.utils import timezone

    upload_url = request.build_absolute_uri(reverse('network_discovery:upload'))

    return _TEMPLATE.format(
        script_version=SCRIPT_VERSION,
        generated_at=timezone.now().strftime('%Y-%m-%d %H:%M %Z'),
        org_name=str(organization.name).replace('#>', ''),
        location_name=str(getattr(location, 'name', location.pk)).replace('#>', ''),
        expires_at=expires_at.strftime('%Y-%m-%d %H:%M %Z'),
        server_url=upload_url,
        token=token_plaintext,
        classify_ports=', '.join(str(p) for p in CLASSIFY_PORTS),
    )

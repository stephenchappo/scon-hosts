#!/bin/bash
# AI Server Setup Script
# Run with: sudo bash /home/scon/ai-server-setup.sh
# Covers: NVIDIA drivers, LVM expansion, zram, ethernet

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }
head_section() { echo -e "\n${BLUE}══════════════════════════════════════${NC}"; echo -e "${BLUE}  $1${NC}"; echo -e "${BLUE}══════════════════════════════════════${NC}"; }

if [ "$EUID" -ne 0 ]; then err "Please run as root: sudo bash $0"; exit 1; fi

# ─── 1. NVIDIA DRIVER ────────────────────────────────────────────────────────
head_section "1/4 — NVIDIA Driver (nvidia-driver-580)"

if nvidia-smi &>/dev/null; then
    log "NVIDIA driver already working, skipping."
else
    log "Updating package lists..."
    apt update -qq

    log "Installing nvidia-driver-580 (recommended for your GPU)..."
    apt install -y nvidia-driver-580

    # Blacklist nouveau to prevent conflicts
    if ! grep -q "nouveau" /etc/modprobe.d/blacklist-nouveau.conf 2>/dev/null; then
        log "Blacklisting nouveau driver..."
        cat > /etc/modprobe.d/blacklist-nouveau.conf << 'EOF'
blacklist nouveau
options nouveau modeset=0
EOF
        update-initramfs -u
    fi

    warn "NVIDIA driver installed. A reboot is required to activate it."
    warn "The script will continue, but GPU won't be active until after reboot."
fi

# ─── 2. LVM EXPANSION ────────────────────────────────────────────────────────
head_section "2/4 — LVM Expansion (using unallocated ~850 GB)"

VG_NAME=$(vgdisplay --short 2>/dev/null | awk 'NR==1{print $1}')
LV_PATH=$(lvdisplay 2>/dev/null | grep "LV Path" | awk '{print $3}')

if [ -z "$VG_NAME" ] || [ -z "$LV_PATH" ]; then
    err "Could not detect VG/LV. Check with: sudo vgdisplay && sudo lvdisplay"
else
    log "VG: $VG_NAME  |  LV: $LV_PATH"
    FREE_PE=$(vgdisplay "$VG_NAME" | grep "Free  PE" | awk '{print $5}')
    log "Free extents available: $FREE_PE"

    if [ "$FREE_PE" -gt 0 ] 2>/dev/null; then
        log "Extending LV to use all free space..."
        lvextend -l +100%FREE "$LV_PATH"

        log "Resizing filesystem online (no downtime)..."
        resize2fs "$LV_PATH"

        log "LVM expansion complete."
        df -h /
    else
        log "No free extents in VG — already fully allocated."
    fi
fi

# ─── 3. ZRAM SWAP ────────────────────────────────────────────────────────────
head_section "3/4 — zram Compressed Swap"

if systemctl is-active --quiet zramswap 2>/dev/null || [ -b /dev/zram0 ]; then
    log "zram already active."
    zramctl
else
    log "Installing zram-config..."
    apt install -y zram-config

    # zram-config sets up zram automatically on boot
    # Also start it now without rebooting
    modprobe zram

    # Configure zram to use 8GB compressed swap (compresses to ~2GB real RAM)
    ZRAM_SIZE="8192MiB"
    ZRAM_DEV=$(zramctl --find --size "$ZRAM_SIZE" --algorithm lz4)
    log "Created zram device: $ZRAM_DEV (${ZRAM_SIZE}, lz4 compression)"

    mkswap "$ZRAM_DEV"
    swapon --priority 10 "$ZRAM_DEV"

    log "zram swap active:"
    zramctl
    cat /proc/swaps
fi

# ─── 4. ETHERNET ─────────────────────────────────────────────────────────────
head_section "4/4 — Ethernet (enp153s0)"

ETH_STATE=$(cat /sys/class/net/enp153s0/operstate 2>/dev/null || echo "unknown")
CARRIER=$(cat /sys/class/net/enp153s0/carrier 2>/dev/null || echo "0")

log "Ethernet interface state: $ETH_STATE | carrier: $CARRIER"

if [ "$CARRIER" = "1" ]; then
    log "Cable detected — bringing interface up and requesting DHCP..."
    ip link set enp153s0 up
    dhclient enp153s0 && log "Ethernet up via DHCP." || warn "DHCP failed, try: sudo dhclient enp153s0"
else
    warn "No Ethernet cable detected (carrier=0). Plug in a cable and run:"
    echo "    sudo ip link set enp153s0 up && sudo dhclient enp153s0"
    echo "  Or to make it persistent via NetworkManager:"
    echo "    sudo nmcli con add type ethernet ifname enp153s0 con-name ethernet"
    echo "    sudo nmcli con up ethernet"
fi

# ─── SUMMARY ─────────────────────────────────────────────────────────────────
head_section "Summary"

echo ""
echo "  Component       Status"
echo "  ─────────────────────────────────────────────────────"

# NVIDIA
if nvidia-smi &>/dev/null; then
    echo -e "  GPU Driver      ${GREEN}Active${NC} — $(nvidia-smi --query-gpu=name --format=csv,noheader)"
else
    echo -e "  GPU Driver      ${YELLOW}Installed — REBOOT REQUIRED${NC}"
fi

# LVM
echo -e "  Storage         $(df -h / | awk 'NR==2{print $2" total, "$4" free ("$5" used)"}')"

# Swap
echo -e "  Swap            $(cat /proc/swaps | awk 'NR>1{print $1" ("$3/1024"MB)"}' | tr '\n' ' ')"

# Network
ETH_NOW=$(cat /sys/class/net/enp153s0/operstate 2>/dev/null)
WIFI_NOW=$(cat /sys/class/net/wlp0s20f3/operstate 2>/dev/null)
echo -e "  Ethernet        ${ETH_NOW}"
echo -e "  WiFi            ${WIFI_NOW}"

echo ""
if ! nvidia-smi &>/dev/null; then
    echo -e "${YELLOW}  ⚠ ACTION REQUIRED: Reboot to activate NVIDIA GPU driver${NC}"
    echo -e "     sudo reboot"
fi
echo ""

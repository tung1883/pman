"""Builds docs/arch/ from selected ArchWiki pages (GFDL 1.3): system administration, networking, storage,
security, virtualization and server software. Pages: arch.<title> (arch.systemd-timers, arch.wireguard).
Fetches politely (1 s delay, cached in .cache/) from wiki.archlinux.org?action=render."""
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetchutil import fetch  # noqa: E402
from htmltext import convert  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "arch", "man", "arch")
BASE = "https://wiki.archlinux.org/title/"

TITLES = """
Systemd;Systemd/Timers;Systemd/User;Systemd/Journal;Systemd-networkd;Systemd-resolved;Systemd-boot;Systemd-nspawn;
Systemd/FAQ;Systemd-timesyncd;Cron;Journalctl;Init;Boot process;Kernel parameters;Sysctl;Kernel modules;Kernel;
Users and groups;Sudo;Polkit;PAM;Security;Security/Fail2ban;Fail2ban;AppArmor;SELinux;Capabilities;Seccomp;Audit framework;
OpenSSH;SSH keys;Secure Shell;Sshd;Mosh;GnuPG;Pass;OpenSSL;Certbot;Let's Encrypt;
Uncomplicated Firewall;Iptables;Nftables;Firewalld;Network configuration;Network configuration/Ethernet;
Network configuration/Wireless;NetworkManager;Netctl;Dnsmasq;Unbound;BIND;Domain name resolution;Hostname;
WireGuard;OpenVPN;OpenVPN;Tcpdump;Wireshark;Nmap;Iproute2;Network bridge;Samba;NFS;Rsync;Wget;CURL;Nginx;Apache HTTP Server;
HAProxy;PostgreSQL;MariaDB;MySQL;SQLite;Redis;Memcached;Postfix;Dovecot;OpenLDAP;Squid;Tor;
LVM;RAID;Mdadm;Btrfs;ZFS;XFS;Ext4;File systems;Fstab;Partitioning;Parted;Fdisk;Gdisk;Dm-crypt;Dm-crypt/Encrypting an entire system;
Dm-crypt/Device encryption;Swap;Zram;S.M.A.R.T.;Hdparm;Benchmarking;Disk cloning;Blkid;Persistent block device naming;
Mkinitcpio;GRUB;Syslinux;Unified Extensible Firmware Interface;UEFI;Arch boot process;Arch Linux;Pacman;Pacman/Tips and tricks;
Pacman/Rosetta;Makepkg;Arch User Repository;Mirrors;Package signing;Reflector;
Docker;Podman;Buildah;Skopeo;LXC;LXD;Incus;Kubernetes;Kubectl;K3s;Libvirt;QEMU;KVM;VirtualBox;Vagrant;Ansible;Terraform;Cgroups;Namespaces;
Linux Containers;Systemd-nspawn;Chroot;Cron;At;Anacron;Logrotate;Syslog-ng;Rsyslog;Logwatch;Monitoring;Prometheus;Grafana;Collectd;
Htop;Strace;Perf;Ltrace;Gdb;Valgrind;Core dump;Debugging/Getting traces;Improving performance;Benchmarking;Power management;
CPU frequency scaling;Cpupower;Laptop;TLP;Time;Systemd-timesyncd;Chrony;Network Time Protocol daemon;Ntp;
Bash;Zsh;Fish;Tmux;GNU Screen;Vim;Nano;Emacs;Git;Git server;Subversion;Make;CMake;GCC;Clang;Rust;Go;Python;Node.js;Java;
Backup programs;Borg;Restic;Duplicity;Rclone;Rdiff-backup;Synchronization and backup programs;Snapper;Timeshift;
Bluetooth;Cups;SANE;Xorg;Wayland;Fonts;Locale;Environment variables;Default applications;XDG Base Directory;Desktop entries;
General recommendations;System maintenance;Pacman/Pacnew and Pacsave;Migration;Mount;Udev;Udisks;Autofs;Sshfs;FUSE;Tmpfs;Procfs;
Dbus;DBus;Cron;Systemd/Writing unit files;Environment variables;List of applications;Core utilities;GNU;Man page;Man;Info;Help:Reading;
Network File System;Ftp;Vsftpd;ProFTPD;Nextcloud;Ntfs-3g;Exfat;Dhcpcd;Dhcp;Dhcpd;Hostapd;Avahi;Ssh;Stunnel;Port forwarding;
Ipv6;IPv6;Netfilter;Traffic shaping;Iperf;Ethtool;Bonding;VLAN;Open vSwitch;Router;Internet sharing;NAT;
"""


def titles():
    seen, out = set(), []
    for t in re.split(r"[;\n]", TITLES):
        t = t.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def is_content(tag, attrs):
    return tag == "div" and "mw-parser-output" in (attrs.get("class") or "")


def main():
    shutil.rmtree(os.path.join(ROOT, "docs", "arch"), ignore_errors=True)
    os.makedirs(OUT)
    n = 0
    for title in titles():
        url = BASE + title.replace(" ", "_") + "?action=render"
        try:
            html = fetch(url, 1.0)
        except Exception as e:
            print("failed", title, str(e)[:40])
            continue
        pid = re.sub(r"[^a-z0-9_.+-]+", "-", title.lower().replace("/", "-")).strip("-")
        text = convert(html, is_content, title, "arch." + pid, "ArchWiki",
                       skip_classes={"mw-editsection", "archwiki-template-meta-related-articles", "toc", "noprint",
                                     "mw-empty-elt", "archwiki-template-meta-state", "mw-references-wrap"},
                       skip_ids={"toc"})
        if len(text) < 600 or "#REDIRECT" in text[:400]:
            continue
        with open(os.path.join(OUT, pid + ".txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        n += 1
    print("arch pages", n)


if __name__ == "__main__":
    main()

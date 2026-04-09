# Set up the device as a hotspot

*When working with the Sensing Garden monitoring station, you might want to access a powered device without internet connection. This guide will show you how you can set it up.*
___

## 1. Ensure NetworkManager is active

On Raspberry Pi OS Bookworm and above, NetworkManager is typically active by default.
You can verify this with:
```bash
systemctl status NetworkManager
```

## 2. Create the Hotspot with nmcli

Replace values in angle brackets with your preferences:

```bash
sudo nmcli connection add con-name <NAME> type wifi ifname wlan0 autoconnect yes ssid <SSID> 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared
```
Example:
```bash
sudo nmcli connection add con-name wlan-sg1 type wifi ifname wlan0 autoconnect yes ssid wlan-sg1 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared
```

## 3. Secure the Hotspot

Set up WPA2 PSK security:

```bash
sudo nmcli connection modify wlan-sg1 wifi-sec.key-mgmt wpa-psk
sudo nmcli connection modify wlan-sg1 wifi-sec.psk "yourpassword" # note: must be at least 8 characters long
```

## 4. Activate the Hotspot

```bash
sudo nmcli connection up wlan-sg1
```

## 5. Connect Devices

Scan for your network SSID (e.g., wlan-sg1) with other devices and use the password to connect.
When connecting, you will be asked for the password.
To access through ssh:
```bash
ssh username@hostname.local # example: ssh sg@sgsca1.local
```

## 6. Additional Tips

You can set the hotspot to always start on boot:

```bash
sudo nmcli connection modify wlan-sg1 connection.autoconnect yes
```
To stop the hotspot:
```bash
sudo nmcli connection down wlan-sg1
```

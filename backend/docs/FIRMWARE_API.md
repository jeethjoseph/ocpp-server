# Non-OCPP Charge Point Firmware Update API

## Overview

This API allows non-OCPP charge points to discover and download firmware updates from the central server. It provides a simple, unauthenticated endpoint for embedded devices to check for the latest available firmware and download it programmatically.

## Use Case

For charge points that **do not support OCPP**, this API enables:
- Automatic firmware update discovery
- Version comparison (charge point compares returned version with current version)
- Secure firmware download with integrity verification via MD5 checksum

## API Endpoint

### Get Latest Firmware

Retrieve information about the latest available firmware version.

```http
GET /api/firmware/latest
```

#### Authentication

**None required** - This is a public endpoint designed for embedded devices without user credentials.

#### Response Format

**Status Code:** `200 OK`

```json
{
  "version": "0.0.2",
  "filename": "0.0.2_simple_ota.bin",
  "download_url": "https://lyncpower.com/firmware/0.0.2_simple_ota.bin",
  "checksum": "d0fd2e471c76287adab65cba424630fa",
  "file_size": 912160
}
```

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Firmware version identifier |
| `filename` | string | Name of the firmware file |
| `download_url` | string | Complete URL to download the firmware binary |
| `checksum` | string | MD5 hash for verifying file integrity |
| `file_size` | integer | File size in bytes |

#### Error Responses

**Status Code:** `404 Not Found`

No active firmware files are available on the server.

```json
{
  "detail": "No firmware files available"
}
```

**Status Code:** `429 Too Many Requests` (if rate limiting is enabled)

Too many requests from the same IP address.

```json
{
  "detail": "Rate limit exceeded"
}
```

## Usage Examples

### ESP32 (Arduino)

```cpp
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Update.h>
#include <MD5Builder.h>

#define CURRENT_VERSION "0.0.1"
#define SERVER_URL "https://lyncpower.com"

void checkForFirmwareUpdate() {
    HTTPClient http;
    http.begin(SERVER_URL "/api/firmware/latest");

    int httpCode = http.GET();

    if (httpCode == 200) {
        String payload = http.getString();

        // Parse JSON response
        DynamicJsonDocument doc(1024);
        DeserializationError error = deserializeJson(doc, payload);

        if (!error) {
            const char* version = doc["version"];
            const char* downloadUrl = doc["download_url"];
            const char* checksum = doc["checksum"];
            int fileSize = doc["file_size"];

            // Compare versions
            if (strcmp(version, CURRENT_VERSION) != 0) {
                Serial.printf("New firmware available: %s\n", version);
                downloadAndInstallFirmware(downloadUrl, checksum, fileSize);
            } else {
                Serial.println("Already on latest version");
            }
        }
    } else if (httpCode == 404) {
        Serial.println("No firmware available on server");
    } else {
        Serial.printf("HTTP error: %d\n", httpCode);
    }

    http.end();
}

void downloadAndInstallFirmware(const char* url, const char* expectedChecksum, int fileSize) {
    HTTPClient http;
    http.begin(url);

    int httpCode = http.GET();

    if (httpCode == 200) {
        WiFiClient* stream = http.getStreamPtr();

        // Start OTA update
        if (Update.begin(fileSize)) {
            Serial.println("Starting firmware update...");

            MD5Builder md5;
            md5.begin();

            size_t written = 0;
            uint8_t buff[128];

            while (http.connected() && (written < fileSize)) {
                size_t size = stream->available();
                if (size) {
                    int c = stream->readBytes(buff, ((size > sizeof(buff)) ? sizeof(buff) : size));
                    Update.write(buff, c);
                    md5.add(buff, c);
                    written += c;

                    // Show progress
                    Serial.printf("Progress: %d%%\n", (written * 100) / fileSize);
                }
                delay(1);
            }

            // Verify checksum
            md5.calculate();
            String calculatedChecksum = md5.toString();

            if (calculatedChecksum.equalsIgnoreCase(expectedChecksum)) {
                if (Update.end()) {
                    Serial.println("Update successful! Rebooting...");
                    ESP.restart();
                } else {
                    Serial.println("Update error: " + String(Update.getError()));
                }
            } else {
                Serial.println("Checksum mismatch! Update aborted.");
                Update.abort();
            }
        }
    }

    http.end();
}

void setup() {
    Serial.begin(115200);

    // Connect to WiFi first...

    // Check for updates on boot
    checkForFirmwareUpdate();

    // Schedule periodic checks (e.g., once per day)
    // ...
}
```

### Python (for testing or other devices)

```python
import requests
import hashlib
import os

CURRENT_VERSION = "0.0.1"
SERVER_URL = "https://lyncpower.com"

def check_for_firmware_update():
    """Check if firmware update is available"""
    try:
        response = requests.get(f"{SERVER_URL}/api/firmware/latest")

        if response.status_code == 200:
            firmware_info = response.json()

            version = firmware_info['version']
            download_url = firmware_info['download_url']
            checksum = firmware_info['checksum']
            file_size = firmware_info['file_size']

            if version != CURRENT_VERSION:
                print(f"New firmware available: {version}")
                download_and_verify_firmware(download_url, checksum, file_size)
            else:
                print("Already on latest version")

        elif response.status_code == 404:
            print("No firmware available on server")
        else:
            print(f"HTTP error: {response.status_code}")

    except Exception as e:
        print(f"Error checking for updates: {e}")

def download_and_verify_firmware(url, expected_checksum, file_size):
    """Download firmware and verify integrity"""
    print(f"Downloading firmware from {url}")

    response = requests.get(url, stream=True)

    if response.status_code == 200:
        # Download to file
        firmware_path = "/tmp/firmware.bin"

        with open(firmware_path, 'wb') as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=4096):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    progress = (downloaded * 100) // file_size
                    print(f"Progress: {progress}%", end='\r')

        print("\nVerifying checksum...")

        # Calculate MD5 checksum
        md5_hash = hashlib.md5()
        with open(firmware_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)

        calculated_checksum = md5_hash.hexdigest()

        if calculated_checksum == expected_checksum:
            print("Checksum verified! Installing firmware...")
            install_firmware(firmware_path)
        else:
            print(f"Checksum mismatch!")
            print(f"Expected: {expected_checksum}")
            print(f"Got: {calculated_checksum}")
            os.remove(firmware_path)
    else:
        print(f"Download failed: HTTP {response.status_code}")

def install_firmware(firmware_path):
    """Install the downloaded firmware"""
    # Implementation depends on your device
    print(f"Installing firmware from {firmware_path}")
    # ... device-specific installation logic ...

if __name__ == "__main__":
    check_for_firmware_update()
```

### cURL (for testing)

```bash
# Get latest firmware info
curl https://lyncpower.com/api/firmware/latest

# Download firmware file
curl -O https://lyncpower.com/firmware/0.0.2_simple_ota.bin

# Verify checksum
md5sum 0.0.2_simple_ota.bin
```

## Integration Best Practices

### 1. Checksum Verification

**Always verify the MD5 checksum** after downloading to ensure:
- File was downloaded completely
- File was not corrupted during transfer
- File integrity is maintained

### 2. Update Frequency

Recommended update check frequency:
- **On boot**: Check for updates when device powers on
- **Daily**: Check once per day during off-peak hours
- **Manual trigger**: Provide a way for users to manually check

**Do not** check too frequently (e.g., every minute) as this wastes bandwidth and may trigger rate limiting.

### 3. Version Comparison

The charge point should:
1. Store its current firmware version
2. Compare with the version returned by the API
3. Only download if versions differ
4. Optionally implement semantic versioning comparison to avoid downgrades

### 4. Error Handling

Handle these scenarios gracefully:
- **404 Not Found**: No firmware available (normal, not an error)
- **Network errors**: Retry with exponential backoff
- **Checksum mismatch**: Do not install, log the error
- **Download interruption**: Resume if supported, or retry

### 5. Update Window

For production charge points:
- Only update when not in use (no active charging session)
- Prefer off-peak hours (e.g., 2-4 AM)
- Notify users before updating (if UI available)

### 6. Rollback Strategy

Implement a rollback mechanism:
- Keep previous firmware version
- If new firmware fails to boot, automatically rollback
- Use a "boot counter" to detect boot loops

### 7. Logging

Log all firmware update activities:
- When check was performed
- Version information received
- Download progress
- Checksum verification results
- Installation status
- Any errors encountered

## Security Considerations

### HTTPS

Always use HTTPS in production to prevent:
- Man-in-the-middle attacks
- Firmware tampering during download
- Eavesdropping

### Checksum Verification

The MD5 checksum provides basic integrity verification. For higher security:
- Consider implementing digital signatures (future enhancement)
- Validate the certificate when using HTTPS

### Rate Limiting

The server may implement rate limiting to prevent abuse. If you receive a 429 error:
- Back off exponentially
- Don't retry immediately
- Typical limit: 60 requests per minute per IP

## Server Behavior

### Latest Firmware Selection

The server determines the "latest" firmware as:
- Filters for `is_active=True` firmware files
- Orders by upload timestamp (`created_at DESC`)
- Returns the most recently uploaded active firmware

### Admin Control

Server administrators can:
- Upload new firmware versions
- Deactivate old versions (sets `is_active=False`)
- When all firmware is deactivated, the endpoint returns 404

## Troubleshooting

### "No firmware files available" (404)

**Cause**: No active firmware files on the server

**Solutions**:
- Contact server administrator to upload firmware
- Check that firmware files are marked as active
- This is not an error - continue normal operation with current firmware

### Checksum Mismatch

**Cause**: File was corrupted during download or transfer

**Solutions**:
- Retry the download
- Check network stability
- Verify sufficient storage space

### Download Timeout

**Cause**: Large firmware file or slow network

**Solutions**:
- Increase timeout value in HTTP client
- Implement resume capability
- Download during better network conditions

### Cannot Connect to Server

**Cause**: Network issues or server down

**Solutions**:
- Verify internet connectivity
- Check server URL is correct
- Retry with exponential backoff
- Log error for later analysis

## FAQ

**Q: Is authentication required?**
A: No, this is a public endpoint designed for embedded devices without credentials.

**Q: How often should I check for updates?**
A: Once per day is recommended. On boot is also a good time to check.

**Q: What if I'm already on the latest version?**
A: Compare the returned version with your current version. If they match, no action needed.

**Q: Can I filter firmware by device model?**
A: Not currently. The endpoint returns the single latest firmware. Model-specific firmware is a future enhancement.

**Q: What happens if download fails?**
A: Retry with exponential backoff. Do not install partial downloads. Always verify the checksum.

**Q: Should I update during active charging?**
A: No, wait until charging session ends to avoid interruption.

## Support

For issues or questions about this API:
- Check the [main system documentation](../../SYSTEM_DOCUMENTATION.md)
- Review server logs for errors
- Contact your system administrator

## Version History

- **v1.0** (2025-11-28): Initial release of public firmware discovery endpoint

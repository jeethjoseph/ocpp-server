import { LogEntry } from "./api-services";

export interface CSVExportOptions {
  filename?: string;
  includeHeaders?: boolean;
}

export function exportLogsToCSV(
  logs: LogEntry[],
  chargerName?: string,
  options: CSVExportOptions = {}
) {
  const {
    filename = `logs_${chargerName || 'charger'}_${new Date().toISOString().split('T')[0]}.csv`,
    includeHeaders = true,
  } = options;

  // Define CSV headers
  const headers = [
    'timestamp',
    'charge_point_id',
    'direction',
    'message_type',
    'status',
    'correlation_id',
    'ocpp_message_type',
    'ocpp_message_id',
    'ocpp_action',
    'payload_json'
  ];

  const csvContent: string[] = [];

  // Add headers if requested
  if (includeHeaders) {
    csvContent.push(headers.join(','));
  }

  // Process each log entry
  logs.forEach(log => {
    const row: (string | number)[] = [];

    // Convert timestamp to local time format
    const localTimestamp = new Date(log.timestamp).toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    });

    // Basic fields
    row.push(escapeCSVField(localTimestamp));
    row.push(escapeCSVField(log.charge_point_id || ''));
    row.push(escapeCSVField(log.direction));
    row.push(escapeCSVField(log.message_type || ''));
    row.push(escapeCSVField(log.status || ''));
    row.push(escapeCSVField(log.correlation_id || ''));

    // Parse OCPP message format: [message_type, message_id, action, payload]
    let ocppMessageType = '';
    let ocppMessageId = '';
    let ocppAction = '';
    let payloadJson = '';

    if (log.payload) {
      if (Array.isArray(log.payload) && log.payload.length >= 4) {
        const [msgType, msgId, action, actualPayload] = log.payload;
        ocppMessageType = msgType === 2 ? 'Call' : msgType === 3 ? 'CallResult' : msgType === 4 ? 'CallError' : String(msgType);
        ocppMessageId = String(msgId);
        ocppAction = String(action);
        payloadJson = actualPayload ? JSON.stringify(actualPayload) : '';
      } else {
        // Not OCPP format, treat as regular payload
        payloadJson = JSON.stringify(log.payload);
      }
    }

    row.push(escapeCSVField(ocppMessageType));
    row.push(escapeCSVField(ocppMessageId));
    row.push(escapeCSVField(ocppAction));
    row.push(escapeCSVField(payloadJson));

    csvContent.push(row.join(','));
  });

  // Create and download the file
  const csvString = csvContent.join('\n');
  const blob = new Blob([csvString], { type: 'text/csv;charset=utf-8;' });

  // Create download link
  const link = document.createElement('a');
  if (link.download !== undefined) {
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', filename);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }
}

function escapeCSVField(field: string | number | null | undefined): string {
  if (field === null || field === undefined) {
    return '';
  }

  const stringField = String(field);

  // If the field contains comma, newline, or double quote, wrap it in double quotes
  if (stringField.includes(',') || stringField.includes('\n') || stringField.includes('"')) {
    // Escape existing double quotes by doubling them
    const escaped = stringField.replace(/"/g, '""');
    return `"${escaped}"`;
  }

  return stringField;
}
// Canonical OCPP 1.6 action names — the closed set offered by the Logs Console
// "Action" filter. Hardcoded (not derived from fetched rows) so the dropdown is
// always complete regardless of what happens to be in the current window.
// See CONTEXT.md "OCPP Action" and ADR 0014.
export const OCPP_ACTIONS = [
  // Charger-initiated (IN)
  "BootNotification",
  "Heartbeat",
  "StatusNotification",
  "MeterValues",
  "StartTransaction",
  "StopTransaction",
  "Authorize",
  "DataTransfer",
  "FirmwareStatusNotification",
  "DiagnosticsStatusNotification",
  // CSMS-initiated (OUT)
  "RemoteStartTransaction",
  "RemoteStopTransaction",
  "ChangeAvailability",
  "ChangeConfiguration",
  "GetConfiguration",
  "Reset",
  "UnlockConnector",
  "ClearCache",
  "UpdateFirmware",
  "GetDiagnostics",
  "TriggerMessage",
  // Frame-type pseudo-actions: the message_type column stores these for OCPP
  // type-3 (CallResult) and type-4 (CallError) reply frames, which carry no
  // action name of their own. Listed here so replies/errors are filterable.
  "CallResult",
  "CallError",
] as const;

export type OcppAction = (typeof OCPP_ACTIONS)[number];

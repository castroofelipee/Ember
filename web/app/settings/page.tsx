import { InviteMembers } from "./invite-members";
import { SettingsForm } from "./settings-form";

export default function SettingsPage() {
  return (
    <div className="hub-page">
      <div className="hub-header">
        <h1 className="auth-title">Settings</h1>
        <p className="auth-subtitle">Preferences and working hours</p>
      </div>
      <div className="hub-content">
        <SettingsForm />
        <div className="settings-divider" />
        <InviteMembers />
      </div>
    </div>
  );
}

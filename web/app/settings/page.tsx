import { CalendarsSection } from "./calendars-section";
import { InviteMembers } from "./invite-members";
import { SettingsForm } from "./settings-form";
import { SettingsHeader } from "./settings-header";

export default function SettingsPage() {
  return (
    <div className="settings-page-layout">
      <SettingsHeader />
      <div className="hub-page settings-page-content">
        <div className="hub-header">
          <h1 className="auth-title">Settings</h1>
          <p className="auth-subtitle">Preferences and working hours</p>
        </div>
        <div className="hub-content">
          <SettingsForm />
          <div className="settings-divider" />
          <CalendarsSection />
          <div className="settings-divider" />
          <InviteMembers />
        </div>
      </div>
    </div>
  );
}

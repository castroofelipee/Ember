import { PreferencesForm } from "./preferences-form";

export default function PreferencesPage() {
  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title">Ember</h1>
        <p className="auth-subtitle">Set your preferences</p>
        <PreferencesForm />
      </div>
    </div>
  );
}

import { SignupForm } from "./signup-form";

export default function SignupPage() {
  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title">Ember</h1>
        <p className="auth-subtitle">Create your account</p>
        <SignupForm />
      </div>
    </div>
  );
}

import { LoginForm } from "./login-form";

export default function LoginPage() {
  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title">Ember</h1>
        <p className="auth-subtitle">Log in to your account</p>
        <LoginForm />
      </div>
    </div>
  );
}

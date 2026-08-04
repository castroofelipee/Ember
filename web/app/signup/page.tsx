import { redirect } from "next/navigation";

import { SignupForm } from "./signup-form";

export const dynamic = "force-dynamic";

export default function SignupPage() {
  if (process.env.SIGNUP_ENABLED?.toLowerCase() === "false") {
    redirect("/login");
  }

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

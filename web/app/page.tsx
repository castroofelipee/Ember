import { redirect } from "next/navigation";

export default function Home() {
  // Let the authenticated route restore the session from the refresh cookie.
  // Its auth guard sends visitors without a valid session back to /login.
  redirect("/calendars");
}

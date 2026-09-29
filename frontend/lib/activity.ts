export type Activity = {
  id: number;
  action: string;
  created_at: string;
  details?: {
    channel?: string;
    code?: string;
    retry?: boolean;
    delivery_id?: number;
    reminder_id?: number;
  };
};

export function activityMessage(activity: Activity) {
  const details = activity.details;
  if (activity.action === "REMINDER_FAILED") {
    const channel =
      details?.channel === "push"
        ? "Browser notification"
        : details?.channel === "email"
          ? "Email reminder"
          : "Reminder delivery";
    const reason =
      details?.code === "push_network" || details?.code === "email_network"
        ? "The worker could not reach the delivery service."
        : details?.code === "email_not_configured"
          ? "Email delivery needs server setup."
          : details?.code === "push_not_configured"
            ? "Browser delivery needs server setup."
            : ["push_http_404", "push_http_410"].includes(details?.code || "")
              ? "This browser subscription expired. Enable browser notifications again on that device."
              : "The delivery service could not accept this notification.";
    return {
      title: `${channel} attempt failed`,
      detail: `${reason} ${details?.retry ? "A retry was scheduled." : "No automatic retries remain for this attempt."} Check Reminders for the in-app reminder.`,
    };
  }
  if (activity.action === "REMINDER_SENT")
    return {
      title: "Reminder processed",
      detail:
        "The reminder is available on the Reminders page. Browser and email delivery are tracked separately.",
    };
  if (activity.action === "REMINDER_PUSH_ACCEPTED")
    return {
      title: "Browser notification sent",
      detail:
        "The push service accepted the notification. Your device controls whether a popup is shown.",
    };
  if (activity.action === "REMINDER_EMAIL_ACCEPTED")
    return { title: "Email reminder sent", detail: "The email service accepted the reminder." };
  return { title: activity.action.toLowerCase().replaceAll("_", " "), detail: "" };
}

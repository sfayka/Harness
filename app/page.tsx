import { redirect } from "next/navigation";

import { TaskBrowser } from "@/components/dashboard/task-browser";

export default function HomePage() {
  if (process.env.NEXT_PUBLIC_HARNESS_DASHBOARD_MODE === "local-static") {
    return <TaskBrowser view="tasks" />;
  }

  redirect("/tasks");
}

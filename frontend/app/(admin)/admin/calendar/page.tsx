import type { Metadata } from "next";
import { CalendarView } from "@/features/admin/calendar/calendar-view";

export const metadata: Metadata = { title: "일정 관리" };
export default function Page() {
  return <CalendarView />;
}

/**
 * Sidebar page configuration.
 * Each tuple contains the page label and its Lucide icon component.
 */
import {
  LayoutDashboard,
  Users,
  ClipboardList,
  CreditCard,
  ShieldCheck,
  FolderKanban,
  Settings,
  Bell,
  Code2,
  Trophy,
} from "lucide-react";

export const links = [
  ["Overview", LayoutDashboard],
  ["Club Hub", Code2],
  ["Members", Users],
  ["Tasks & Projects", ClipboardList],
  ["Leaderboard", Trophy],
  ["Notifications", Bell],
  ["Digital ID Cards", CreditCard],
  ["Verification", ShieldCheck],
  ["Teams", FolderKanban],
  ["Settings", Settings],
];

"use client";

import { useState } from "react";
import { PageTitle } from "@/components/ui/primitives";
import { UsersTab } from "./users-tab";
import { RegistryTab } from "./registry-tab";
import { SourcesTab } from "@/components/sources/sources-tab";

const TABS = ["users", "roles", "departments", "types", "sources"] as const;
type Tab = (typeof TABS)[number];

export function AdminPanel() {
    const [tab, setTab] = useState<Tab>("users");
    return (
        <div className="mx-auto max-w-6xl p-6">
            <PageTitle sub="Users, roles, departments, document types, and source configuration.">Admin</PageTitle>
            <div className="mb-6 flex gap-1 border-b border-line">
                {TABS.map((item) => (
                    <button key={item} onClick={() => setTab(item)} className={`border-b-2 px-3 py-2 text-sm ${tab === item ? "border-accent text-ink" : "border-transparent text-inkSoft"}`}>
                        {item === "types" ? "Document types" : item[0].toUpperCase() + item.slice(1)}
                    </button>
                ))}
            </div>
            {tab === "users" ? <UsersTab /> : null}
            {tab === "roles" ? <RegistryTab title="Roles" endpoint="roles" bodyKey="name" /> : null}
            {tab === "departments" ? <RegistryTab title="Departments" endpoint="departments" bodyKey="name" /> : null}
            {tab === "types" ? <RegistryTab title="Document types" endpoint="document-types" bodyKey="label" /> : null}
            {tab === "sources" ? <SourcesTab /> : null}
        </div>
    );
}
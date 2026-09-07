import { CommandCenter } from "@/components/command-center/CommandCenter";
import { EntityReadinessPanel } from "@/components/command-center/EntityReadinessPanel";

export default function CommandCenterPage() {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-auto bg-[#050705]">
      <EntityReadinessPanel />
      <div className="min-h-0 flex-1">
        <CommandCenter />
      </div>
    </div>
  );
}

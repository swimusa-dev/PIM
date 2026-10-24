// 1.3 metadata layer, RBAC-02, IMP-11, GOV-04, GOV-07: Admin with sub-tabs for attributes, groups,
// option lists, families, channels, user roles, ERP defects, attribute usage, and telemetry.

import { useNavigate, useParams } from "react-router-dom";
import { Tabs } from "../components/Common";
import { AttributesTab } from "../admin/Attributes";
import { GroupsTab, FamiliesTab } from "../admin/Groups";
import { OptionListsTab } from "../admin/OptionLists";
import { ChannelsTab } from "../admin/Channels";
import { UserRolesTab } from "../admin/UserRoles";
import { ErpDefectsTab, AttributeUsageTab } from "../admin/Reports";
import { TelemetryTab } from "../admin/Telemetry";

const TABS = [
  { key: "attributes", label: "Attributes" },
  { key: "groups", label: "Groups" },
  { key: "option-lists", label: "Option lists" },
  { key: "families", label: "Families" },
  { key: "channels", label: "Channels" },
  { key: "user-roles", label: "User roles" },
  { key: "erp-defects", label: "ERP defects" },
  { key: "attribute-usage", label: "Attribute usage" },
  { key: "telemetry", label: "Telemetry" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

export function AdminPage() {
  const { tab } = useParams();
  const navigate = useNavigate();
  const active: TabKey = (TABS.find((t) => t.key === tab)?.key ?? "attributes") as TabKey;
  return (
    <div>
      <div className="page-header">
        <h1>Admin</h1>
        <span className="muted small">Metadata is the product model. Changes here apply to every screen, import and export.</span>
      </div>
      <Tabs<TabKey> tabs={[...TABS]} value={active} onChange={(k) => navigate(`/admin/${k}`)} />
      {active === "attributes" && <AttributesTab />}
      {active === "groups" && <GroupsTab />}
      {active === "option-lists" && <OptionListsTab />}
      {active === "families" && <FamiliesTab />}
      {active === "channels" && <ChannelsTab />}
      {active === "user-roles" && <UserRolesTab />}
      {active === "erp-defects" && <ErpDefectsTab />}
      {active === "attribute-usage" && <AttributeUsageTab />}
      {active === "telemetry" && <TelemetryTab />}
    </div>
  );
}

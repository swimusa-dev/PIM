// AI-02: Admin > AI tab: Brand voice editor and Prompt templates manager as sub-tabs.

import { useState } from "react";
import { Tabs } from "../components/Common";
import { BrandVoicesTab } from "./BrandVoices";
import { PromptTemplatesTab } from "./PromptTemplates";

type Sub = "templates" | "voices";

export function AiAdminTab() {
  const [sub, setSub] = useState<Sub>("templates");
  return (
    <div className="stack">
      <Tabs<Sub>
        value={sub}
        onChange={setSub}
        tabs={[
          { key: "templates", label: "Prompt templates" },
          { key: "voices", label: "Brand voice" },
        ]}
      />
      {sub === "templates" && <PromptTemplatesTab />}
      {sub === "voices" && <BrandVoicesTab />}
    </div>
  );
}

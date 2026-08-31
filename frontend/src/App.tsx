import { SiteNav } from "@/components/site/SiteNav";
import { SiteFooter } from "@/components/site/SiteFooter";
import { FleetPage } from "@/components/pages/FleetPage";

export default function App() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <SiteNav />
      <main>
        <FleetPage />
      </main>
      <SiteFooter />
    </div>
  );
}

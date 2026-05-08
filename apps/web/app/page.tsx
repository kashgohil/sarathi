import { Header } from "@/components/header";
import { Hero } from "@/components/hero";
import { Verse } from "@/components/verse";
import { HowItWorks } from "@/components/how-it-works";
import { PrivacyStripe } from "@/components/privacy-stripe";
import { Specs } from "@/components/specs";
import { Footer } from "@/components/footer";

export default function HomePage() {
  return (
    <main className="relative">
      <Header />
      <Hero />
      <Verse />
      <HowItWorks />
      <PrivacyStripe />
      <Specs />
      <Footer />
    </main>
  );
}

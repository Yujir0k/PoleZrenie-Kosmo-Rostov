'use client';

import Image from 'next/image';
import { ArrowRight } from 'lucide-react';

import { BrandMark } from './workspace/field-sidebar';
import { BRAND_NAME } from '@/lib/brand';

interface LandingPageProps {
  onOpen: () => void;
}

export default function LandingPage({ onOpen }: LandingPageProps) {
  const openWorkspace = () => {
    window.location.hash = 'workspace';
    onOpen();
  };

  return (
    <main className="landing-page">
      <header className="landing-header">
        <button
          className="landing-logo"
          onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
          aria-label="В начало страницы"
        >
          <BrandMark />
          <span>{BRAND_NAME}</span>
        </button>

        <button
          className="landing-primary landing-header-cta landing-login"
          type="button"
          disabled
          title="Авторизация появится позже"
        >
          Войти
        </button>
      </header>

      <section className="landing-hero">
        <div className="topography" aria-hidden="true" />

        <div className="hero-copy">
          <h1>Состояние каждого поля — в одном понятном окне</h1>
          <p>
            Спутниковые наблюдения, восстановленный NDVI и объяснимые аномалии —
            без ручной подготовки данных.
          </p>
          <button className="landing-primary hero-cta" onClick={openWorkspace}>
            Начать мониторинг
            <ArrowRight size={19} aria-hidden="true" />
          </button>
        </div>

        <div className="hero-preview">
          <Image
            className="hero-product-image"
            src="/landing-dashboard-v2.png"
            alt="Интерфейс мониторинга поля со спутниковой картой, аномалией и графиком NDVI"
            width={1536}
            height={1024}
            priority
            sizes="(max-width: 860px) 100vw, 62vw"
          />
        </div>
      </section>

      <footer className="landing-proof" aria-label="Источники данных">
        <span>© {BRAND_NAME} 2026</span>
        <div>
          <strong>Sentinel‑2</strong>
          <i aria-hidden="true" />
          <strong>Landsat 8/9</strong>
          <i aria-hidden="true" />
          <strong>MODIS</strong>
          <i aria-hidden="true" />
          <strong>ERA5‑Land</strong>
        </div>
      </footer>
    </main>
  );
}

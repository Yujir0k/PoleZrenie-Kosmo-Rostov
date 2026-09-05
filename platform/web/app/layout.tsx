import type { Metadata } from 'next';
import { Manrope } from 'next/font/google';
import { BRAND_DESCRIPTION, BRAND_NAME } from '@/lib/brand';
import './globals.css';

const manrope = Manrope({
  variable: '--font-manrope',
  subsets: ['cyrillic', 'latin'],
});

export const metadata: Metadata = {
  title: `${BRAND_NAME} — мониторинг вегетации`,
  description: BRAND_DESCRIPTION,
  icons: { icon: '/polezrenie-mark.svg' },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body className={`${manrope.variable} antialiased`}>{children}</body>
    </html>
  );
}

import type { Metadata } from 'next';
import { Manrope, Prata } from 'next/font/google';
import './globals.css';

const manrope = Manrope({
  variable: '--font-manrope',
  subsets: ['cyrillic', 'latin'],
});

const prata = Prata({
  variable: '--font-prata',
  weight: '400',
  subsets: ['cyrillic', 'latin'],
});

export const metadata: Metadata = {
  title: 'VIGOR — спутниковый мониторинг полей',
  description:
    'Интерактивный прототип мониторинга вегетации, восстановления NDVI и объяснения аномалий.',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body className={`${manrope.variable} ${prata.variable}`}>
        {children}
      </body>
    </html>
  );
}

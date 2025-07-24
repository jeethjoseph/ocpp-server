'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useTheme } from '@/contexts/ThemeContext';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';

const navigation = [
  { name: 'Dashboard', href: '/' },
  { name: 'Stations', href: '/stations' },
  { name: 'Chargers', href: '/chargers' },
];

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const { user, signOut, loading } = useAuth();

  const themeIcons = {
    light: '☀️',
    dark: '🌙',
    system: '💻',
  };

  const cycleTheme = () => {
    const themes: ('light' | 'dark' | 'system')[] = ['light', 'dark', 'system'];
    const currentIndex = themes.indexOf(theme);
    const nextIndex = (currentIndex + 1) % themes.length;
    setTheme(themes[nextIndex]);
  };

  const currentIcon = themeIcons[theme];

  const handleSignOut = async () => {
    const { error } = await signOut();
    if (!error) {
      router.push('/auth');
    }
  };

  return (
    <nav className="bg-card shadow border-b border-border transition-colors duration-300">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16">
          <div className="flex">
            <div className="flex-shrink-0 flex items-center">
              <h1 className="text-xl font-bold text-card-foreground">
                OCPP Admin
              </h1>
            </div>
            <div className="hidden sm:ml-6 sm:flex sm:space-x-8">
              {navigation.map((item) => (
                <Link
                  key={item.name}
                  href={item.href}
                  className={`inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium transition-colors duration-200 ${
                    pathname === item.href
                      ? 'border-primary text-card-foreground'
                      : 'border-transparent text-muted-foreground hover:border-border hover:text-card-foreground'
                  }`}
                >
                  {item.name}
                </Link>
              ))}
            </div>
          </div>
          <div className="flex items-center space-x-4">
            <button
              onClick={cycleTheme}
              className="p-2 rounded-md text-muted-foreground hover:text-card-foreground hover:bg-accent transition-colors duration-200 text-lg"
              title={`Current theme: ${theme}. Click to cycle themes.`}
            >
              {currentIcon}
            </button>
            
            {user ? (
              <div className="flex items-center space-x-3">
                <span className="text-sm text-muted-foreground">
                  {user.email}
                </span>
                <Button
                  onClick={handleSignOut}
                  variant="outline"
                  size="sm"
                  disabled={loading}
                >
                  {loading ? 'Signing out...' : 'Sign Out'}
                </Button>
              </div>
            ) : (
              <Button
                onClick={() => router.push('/auth')}
                variant="default"
                size="sm"
              >
                Sign In
              </Button>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTheme } from '@/contexts/ThemeContext';
import { SignInButton, SignedIn, SignedOut, UserButton } from '@clerk/nextjs';
import { Button } from '@/components/ui/button';
import { useUserRole } from './RoleWrapper';

const userNavigation = [
  { name: 'Dashboard', href: '/dashboard' },
  { name: 'Stations', href: '/stations' },
  { name: 'My Sessions', href: '/my-sessions' },
];

const adminNavigation = [
  { name: 'Admin Dashboard', href: '/admin' },
  { name: 'Stations', href: '/admin/stations' },
  { name: 'Chargers', href: '/admin/chargers' },
  { name: 'Users', href: '/admin/users' },
];

export default function Navbar() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const { role, isAdmin, isUser, isLoaded } = useUserRole();

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

  // Determine which navigation to show
  const navigation = isAdmin ? adminNavigation : userNavigation;

  return (
    <nav className="bg-card shadow border-b border-border transition-colors duration-300">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16">
          <div className="flex">
            <div className="flex-shrink-0 flex items-center">
              <Link href={isAdmin ? "/admin" : "/dashboard"}>
                <h1 className="text-xl font-bold text-card-foreground hover:text-primary transition-colors">
                  OCPP {isAdmin ? 'Admin' : 'Dashboard'}
                </h1>
              </Link>
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
            
            <SignedIn>
              {isLoaded && role && (
                <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                  isAdmin 
                    ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' 
                    : 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200'
                }`}>
                  {role}
                </span>
              )}
              <UserButton />
            </SignedIn>
            <SignedOut>
              <SignInButton>
                <Button variant="default" size="sm">
                  Sign In
                </Button>
              </SignInButton>
            </SignedOut>
          </div>
        </div>
      </div>
    </nav>
  );
}
import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server'
import { clerkClient } from '@clerk/nextjs/server'
import { NextResponse } from 'next/server'

const isProtectedRoute = createRouteMatcher([
  '/',
  '/dashboard(.*)',
  '/admin(.*)',
  '/stations(.*)',
  '/chargers(.*)',
  '/api(.*)',
])

const isPublicRoute = createRouteMatcher([
  '/auth(.*)',
  '/sign-up(.*)',
  '/sign-in(.*)',
])

async function assignDefaultRole(userId: string) {
  try {
    const client = await clerkClient();
    
    // First, fetch the current user to check if they actually have a role
    const user = await client.users.getUser(userId);
    const currentRole = user.publicMetadata?.role;
    
    console.log(`🔍 assignDefaultRole check - User ${userId} current role in Clerk: ${currentRole || 'none'}`);
    
    // Only set default USER role if no role exists
    if (!currentRole) {
      await client.users.updateUserMetadata(userId, {
        publicMetadata: { role: "USER" }
      });
      console.log(`✅ Assigned default USER role to user ${userId}`);
    } else {
      console.log(`⚠️  User ${userId} already has role: ${currentRole}, NOT overwriting`);
    }
  } catch (error) {
    console.error("❌ Failed to set default role:", error);
  }
}

function handleRoleBasedRouting(req: any, role: string) {
  const { pathname } = req.nextUrl;
  
  console.log(`🔄 handleRoleBasedRouting - Path: ${pathname}, Role: ${role}`);
  
  // Admin routes - only admins can access
  if (pathname.startsWith('/admin')) {
    if (role !== 'ADMIN') {
      console.log(`❌ Non-admin user attempted to access admin route: ${pathname}`);
      return NextResponse.redirect(new URL('/dashboard', req.url));
    }
    console.log(`✅ Admin accessing admin route: ${pathname}`);
    return NextResponse.next();
  }
  
  // Redirect admin users from regular dashboard to admin dashboard
  if (pathname === '/dashboard' && role === 'ADMIN') {
    console.log(`🔄 Redirecting admin from /dashboard to /admin`);
    return NextResponse.redirect(new URL('/admin', req.url));
  }
  
  // Redirect admin users from root to admin dashboard
  if (pathname === '/' && role === 'ADMIN') {
    console.log(`🔄 Redirecting admin from / to /admin`);
    return NextResponse.redirect(new URL('/admin', req.url));
  }
  
  // Redirect regular users from root to user dashboard  
  if (pathname === '/' && role === 'USER') {
    console.log(`🔄 Redirecting user from / to /dashboard`);
    return NextResponse.redirect(new URL('/dashboard', req.url));
  }
  
  console.log(`✅ Allowing access to ${pathname}`);
  return NextResponse.next();
}

export default clerkMiddleware(async (auth, req) => {
  console.log(`🚀 Middleware triggered for: ${req.nextUrl.pathname}`);
  
  // Skip processing for public routes
  if (isPublicRoute(req)) {
    console.log(`✅ Public route, skipping: ${req.nextUrl.pathname}`);
    return NextResponse.next();
  }
  
  if (isProtectedRoute(req)) {
    const { userId, sessionClaims } = await auth.protect();
    
    if (!userId) {
      return NextResponse.next(); // This should redirect to sign-in
    }
    
    // Get role from session claims
    const publicMetadata = sessionClaims?.publicMetadata as { role?: string } | undefined;
    const role = publicMetadata?.role;
    
    // If no role is set in session, check actual role in Clerk database
    if (!role) {
      console.log(`🔍 User ${userId} has no role in session, fetching from Clerk database...`);
      
      try {
        const client = await clerkClient();
        const user = await client.users.getUser(userId);
        const actualRole = user.publicMetadata?.role as string;
        
        console.log(`🔍 Actual role from Clerk database: ${actualRole || 'none'}`);
        
        if (actualRole) {
          // Use the actual role from database
          console.log(`✅ Using database role: ${actualRole}`);
          return handleRoleBasedRouting(req, actualRole);
        } else {
          // No role exists, set default
          console.log(`🔧 No role found, assigning default USER`);
          assignDefaultRole(userId);
          return handleRoleBasedRouting(req, "USER");
        }
      } catch (error) {
        console.error("❌ Failed to fetch user from Clerk:", error);
        return handleRoleBasedRouting(req, "USER");
      }
    }
    
    console.log(`✅ User ${userId} has role: ${role}`);
    
    // Handle routing based on role
    return handleRoleBasedRouting(req, role);
  }
  
  return NextResponse.next();
})

export const config = {
  matcher: [
    // Skip Next.js internals and all static files, unless found in search params
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    // Always run for API routes
    '/(api|trpc)(.*)',
  ],
}
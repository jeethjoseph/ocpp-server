import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server'
import { clerkClient } from '@clerk/nextjs/server'
import { NextResponse } from 'next/server'

const isProtectedRoute = createRouteMatcher([
  '/',
  '/admin(.*)',
  '/stations(.*)',
  '/charge(.*)',
  '/scanner(.*)',
  '/my-sessions(.*)',
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
    
    // Only set default USER role if no role exists
    if (!currentRole) {
      await client.users.updateUserMetadata(userId, {
        publicMetadata: { role: "USER" }
      });
    }
  } catch (error) {
    console.error("Failed to set default role:", error);
  }
}

function handleRoleBasedRouting(req: any, role: string) {
  const { pathname } = req.nextUrl;
  
  // Admin routes - only admins can access
  if (pathname.startsWith('/admin')) {
    if (role !== 'ADMIN') {
      return NextResponse.redirect(new URL('/', req.url));
    }
    return NextResponse.next();
  }
  
  // Redirect admin users from root to admin dashboard
  if (pathname === '/' && role === 'ADMIN') {
    return NextResponse.redirect(new URL('/admin', req.url));
  }
  
  // Regular users can access root directly - no redirect needed
  // Root page now has proper RBAC to show user content
  
  return NextResponse.next();
}

export default clerkMiddleware(async (auth, req) => {
  // Skip processing for public routes
  if (isPublicRoute(req)) {
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
      try {
        const client = await clerkClient();
        const user = await client.users.getUser(userId);
        const actualRole = user.publicMetadata?.role as string;
        
        if (actualRole) {
          // Use the actual role from database
          return handleRoleBasedRouting(req, actualRole);
        } else {
          // No role exists, set default
          assignDefaultRole(userId);
          return handleRoleBasedRouting(req, "USER");
        }
      } catch (error) {
        console.error("Failed to fetch user from Clerk:", error);
        return handleRoleBasedRouting(req, "USER");
      }
    }
    
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
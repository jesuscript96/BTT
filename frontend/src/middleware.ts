import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server'
import { NextResponse } from 'next/server'

// Everything is gated behind auth except the auth pages themselves. The root
// route `/` is the data dashboard (it fetches on mount), so there is no public
// landing to leave open.
const isPublicRoute = createRouteMatcher([
  '/sign-in(.*)',
  '/sign-up(.*)',
])

export default clerkMiddleware(async (auth, request) => {
  if (isPublicRoute(request)) return

  const { userId } = await auth()
  if (userId) return

  // Redirigimos a mano en vez de con `auth.protect()`: en Next 16 el middleware
  // corre en runtime de Node, y Clerk resuelve su signInUrl leyendo
  // NEXT_PUBLIC_CLERK_SIGN_IN_URL de process.env. Si esa var no está presente en
  // runtime, cae a "" y `new URL("", req.url)` resuelve a la página ACTUAL: el
  // usuario sin sesión se queda en bucle en vez de ir al login.
  // Ver https://github.com/clerk/javascript/issues/8302
  const signInUrl = new URL('/sign-in', request.url)
  signInUrl.searchParams.set('redirect_url', request.url)
  return NextResponse.redirect(signInUrl)
})

export const config = {
  matcher: [
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    '/(api|trpc)(.*)',
  ],
}

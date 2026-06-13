import { clerkMiddleware } from '@clerk/nextjs/server'

// AUTH PAUSADO — descomentar cuando se reactive Fase 2
// const isPublicRoute = createRouteMatcher([
//   '/sign-in(.*)',
//   '/sign-up(.*)',
// ])

export default clerkMiddleware(() => {
  // Auth desactivado temporalmente
  // if (!isPublicRoute(request)) {
  //   auth().protect()
  // }
})

export const config = {
  matcher: [
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    '/(api|trpc)(.*)',
  ],
}

WEBAPI.SVGGRADIENTELEMENT-SPREADMETHOD(1) Sandbox manual WEBAPI.SVGGRADIENTELEMENT-SPREADMETHOD(1)

       NAME

       SVGGradientElement: spreadMethod property - The spreadMethod read-only property of the SVGGradientElement interface reflects the spreadMethod attribute of the given element. It takes o

       SVGGRADIENTELEMENT: SPREADMETHOD PROPERTY

       The spreadMethod read-only property of the SVGGradientElement interface reflects the spreadMethod attribute of the given element. It takes one of the SVG_SPREADMETHOD_* constants defined on this interface.

       VALUE

       An SVGAnimatedEnumeration.

       EXAMPLES

       ACCESSING THE SPREADMETHOD PROPERTY

         <svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">
           <defs>
             <linearGradient id="gradient2" spreadMethod="reflect">
               <stop offset="0%" stop-color="red" />
               <stop offset="50%" stop-color="yellow" />
               <stop offset="100%" stop-color="blue" />
             </linearGradient>
           </defs>
           <rect x="10" y="10" width="180" height="180" fill="url(#gradient2)" />
         </svg>

         const gradient = document.getElementById("gradient2");
         console.log(gradient.spreadMethod.baseVal); // Output: 2 (SVG_SPREADMETHOD_REFLECT)

       SPECIFICATIONS

       BROWSER COMPATIBILITY

Web APIs manual                         from the official documentation

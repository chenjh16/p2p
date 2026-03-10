## Animation and Transition Rules

When you detect that adjacent slides meet the following conditions, consider adding animation or transition effects:

1. **Morph Transition** (most recommended): Two pages have similar layout structures but some elements change in position, size, or content. In this case:
   - Add a Morph transition to the latter page's `<p:sld>`:
     ```xml
     <mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
                          xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main">
       <mc:Choice Requires="p14">
         <p:transition spd="slow" p14:dur="1500">
           <p14:morph option="byObject"/>
         </p:transition>
       </mc:Choice>
       <mc:Fallback>
         <p:transition spd="slow"><p:fade/></p:transition>
       </mc:Fallback>
     </mc:AlternateContent>
     ```
   - Ensure corresponding elements across both pages share the same `name` attribute for Morph matching

2. **Progressive Reveal**: When the latter page has additional elements compared to the former, add entrance animations for the new elements (via `<p:timing>`)

3. **Page Transitions**: When two pages have completely different content, use appropriate transition effects (`<p:fade/>`, `<p:push/>`, `<p:wipe/>`, etc.)

4. **Use Restraint**: Only add animations when they genuinely enhance the presentation. Avoid flashy, meaningless effects.
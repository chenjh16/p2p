## 动画和转场规则

当你检测到相邻 slides 满足以下条件时，考虑添加动画或转场效果：

1. **Morph 转场**（最推荐）：两页有相似的布局结构但某些元素在位置、大小或内容上发生变化。此时：
   - 在后一页的 `<p:sld>` 中添加 Morph 转场：
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
   - 确保两页中对应的元素共享相同的 `name` 属性以实现 Morph 匹配

2. **逐步揭示**：当后一页相比前一页有新增元素时，为新元素添加入场动画（通过 `<p:timing>`）

3. **页面转场**：当两页内容完全不同时，使用适当的转场效果（`<p:fade/>`、`<p:push/>`、`<p:wipe/>` 等）

4. **克制使用**：仅在动画真正能增强演示效果时才添加。避免花哨、无意义的效果。
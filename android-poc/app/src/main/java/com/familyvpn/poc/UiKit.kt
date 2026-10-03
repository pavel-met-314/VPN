package com.familyvpn.poc

import android.app.Activity
import android.content.res.Configuration
import android.content.res.ColorStateList
import android.graphics.Canvas
import android.graphics.ColorFilter
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.view.ContextThemeWrapper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.widget.Button
import android.widget.EditText
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

internal class UiKit(val activity: Activity) {
    val dark = when (AppPreferences.theme(activity)) {
        "dark" -> true
        "light" -> false
        else -> activity.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK == Configuration.UI_MODE_NIGHT_YES
    }
    val context = ContextThemeWrapper(AppPreferences.localized(activity),
        if (dark) android.R.style.Theme_Material_NoActionBar else android.R.style.Theme_Material_Light_NoActionBar)
    val foreground = if (dark) 0xfff4f2ff.toInt() else 0xff15152b.toInt()
    val secondary = if (dark) 0xffb5b4d6.toInt() else 0xff606083.toInt()
    val accent = if (dark) 0xffb299ff.toInt() else 0xff7350e8.toInt()
    val border = if (dark) 0xff414357.toInt() else 0xffdddaef.toInt()
    val surface = if (dark) 0xf017191f.toInt() else 0xf0ffffff.toInt()
    val error = if (dark) 0xffff657c.toInt() else 0xffcf254c.toInt()
    val success = if (dark) 0xff84dbb6.toInt() else 0xff18764e.toInt()
    fun dp(value: Int): Int = (value * activity.resources.displayMetrics.density).toInt()
    fun s(id: Int, vararg args: Any): String = context.getString(id, *args)
    fun shape(fill: Int = surface, stroke: Int = border, radius: Int = 18) = GradientDrawable().apply {
        setColor(fill); cornerRadius = dp(radius).toFloat(); setStroke(dp(1), stroke)
    }
    fun column(): LinearLayout = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
    fun line(): LinearLayout = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
    fun params(bottom: Int = 12) = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(bottom) }
    fun text(value: String, size: Float = 16f, bold: Boolean = false): TextView = TextView(context).apply {
        text = value; textSize = size; setTextColor(this@UiKit.foreground)
        if (bold) typeface = Typeface.create("sans-serif", Typeface.BOLD)
    }
    fun card(parent: LinearLayout): LinearLayout = column().apply {
        background = shape(); setPadding(dp(18), dp(18), dp(18), dp(6)); parent.addView(this, params(14))
    }
    fun button(value: String, primary: Boolean = false, danger: Boolean = false, icon: Int? = null, action: () -> Unit): Button = Button(context).apply {
        text = value; textSize = 15f; isAllCaps = false
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        setTextColor(if (danger) this@UiKit.error else if (primary) 0xff18122d.toInt() else this@UiKit.foreground)
        minHeight = dp(52); minimumHeight = dp(52)
        setPadding(dp(16), dp(12), dp(16), dp(12))
        background = if (primary) GradientDrawable(GradientDrawable.Orientation.TL_BR,
            intArrayOf(0xffb5a0ff.toInt(), 0xffa38aec.toInt())).apply { cornerRadius = dp(14).toFloat() }
            else shape(if (danger) (if (dark) 0xff2b1c25.toInt() else 0xfffff0f4.toInt()) else surface,
                if (danger) this@UiKit.error else border, 14)
        icon?.let { id ->
            val drawable = context.getDrawable(id)!!.mutate()
            drawable.setTint(if (danger) this@UiKit.error else if (primary) 0xff18122d.toInt() else accent)
            drawable.setBounds(0, 0, dp(24), dp(24)); setCompoundDrawablesRelative(drawable, null, null, null)
            compoundDrawablePadding = dp(10)
        }
        setOnClickListener { action() }
    }
    fun iconButton(icon: Int, description: String, action: () -> Unit): ImageButton = ImageButton(context).apply {
        setImageResource(icon)
        imageTintList = ColorStateList.valueOf(accent)
        scaleType = ImageView.ScaleType.CENTER
        contentDescription = description
        minimumWidth = dp(48); minimumHeight = dp(48)
        setPadding(dp(12), dp(12), dp(12), dp(12))
        background = shape(radius = 14)
        setOnClickListener { action() }
    }
    fun input(hintText: String, input: Int, icon: Int): EditText = EditText(context).apply {
        hint = hintText; inputType = input; setSingleLine(true); textSize = 16f
        typeface = Typeface.create("sans-serif", Typeface.NORMAL)
        setTextColor(this@UiKit.foreground); setHintTextColor(secondary); background = shape(surface, border, 13)
        setPadding(dp(14), dp(12), dp(14), dp(12)); minHeight = dp(52)
        val drawable = context.getDrawable(icon)!!.mutate().apply { setTint(secondary); setBounds(0, 0, dp(22), dp(22)) }
        setCompoundDrawablesRelative(drawable, null, null, null); compoundDrawablePadding = dp(12)
        backgroundTintList = null
    }
    fun root(title: View): Pair<LinearLayout, ScrollView> {
        val layout = column().apply { setPadding(dp(18), dp(22), dp(18), dp(18)) }
        layout.addView(title, params(20))
        val scroll = ScrollView(context).apply {
            isFillViewport = true; background = Atmosphere(dark); addView(layout)
            setOnApplyWindowInsetsListener { view, insets ->
                if (Build.VERSION.SDK_INT >= 30) {
                    val edges = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.ime())
                    view.setPadding(edges.left, edges.top, edges.right, edges.bottom)
                } else {
                    @Suppress("DEPRECATION")
                    view.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop, insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
                }
                insets
            }
        }
        @Suppress("DEPRECATION")
        activity.window.decorView.systemUiVisibility = if (dark) 0 else View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or
            (if (Build.VERSION.SDK_INT >= 26) View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR else 0)
        if (Build.VERSION.SDK_INT >= 30) activity.window.insetsController?.setSystemBarsAppearance(
            if (dark) 0 else WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS,
            WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS,
        )
        activity.setContentView(scroll); scroll.requestApplyInsets()
        return layout to scroll
    }
    fun tint(view: android.widget.CompoundButton) { view.buttonTintList = ColorStateList.valueOf(accent); view.setTextColor(foreground) }
    private class Atmosphere(val dark: Boolean) : Drawable() {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        override fun draw(canvas: Canvas) {
            canvas.drawColor(if (dark) 0xff101216.toInt() else 0xfffaf9ff.toInt())
            val width = bounds.width().toFloat()
            paint.color = if (dark) 0xff222333.toInt() else 0xffeeebff.toInt()
            canvas.drawCircle(width * 1.13f, -width * 0.15f, width * 0.66f, paint)
            paint.color = if (dark) 0xff29273c.toInt() else 0xffe5e0fb.toInt()
            canvas.drawCircle(width * 1.25f, -width * 0.18f, width * 0.51f, paint)
        }
        override fun setAlpha(alpha: Int) { paint.alpha = alpha }
        override fun setColorFilter(colorFilter: ColorFilter?) { paint.colorFilter = colorFilter }
        @Deprecated("Drawable opacity") override fun getOpacity() = PixelFormat.OPAQUE
    }
}

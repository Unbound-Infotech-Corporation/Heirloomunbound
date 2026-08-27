using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Windows.System;

namespace Heirloom.Controls;

public sealed partial class PttButton : UserControl
{
    public event RoutedEventHandler? Pressed;
    public event RoutedEventHandler? Released;

    private bool _pointerHeld;
    private bool _keyHeld;

    public PttButton()
    {
        InitializeComponent();
        Loaded += (_, _) => ApplyArmed(IsArmed);
        Unloaded += (_, _) => ForceEnd();
        Face.AddHandler(PointerPressedEvent, new PointerEventHandler(OnPressed), handledEventsToo: true);
        Face.AddHandler(PointerReleasedEvent, new PointerEventHandler(OnReleased), handledEventsToo: true);
        Face.AddHandler(PointerCanceledEvent, new PointerEventHandler(OnCanceled), handledEventsToo: true);
        Face.AddHandler(PointerCaptureLostEvent, new PointerEventHandler(OnCaptureLost), handledEventsToo: true);
        AddHandler(KeyDownEvent, new KeyEventHandler(OnKeyDownHold), handledEventsToo: true);
        AddHandler(KeyUpEvent, new KeyEventHandler(OnKeyUpHold), handledEventsToo: true);
    }

    public bool IsArmed
    {
        get => (bool)GetValue(IsArmedProperty);
        set => SetValue(IsArmedProperty, value);
    }

    public static readonly DependencyProperty IsArmedProperty =
        DependencyProperty.Register(nameof(IsArmed), typeof(bool), typeof(PttButton), new PropertyMetadata(false, OnArmed));

    private static void OnArmed(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is PttButton btn)
        {
            btn.ApplyArmed((bool)e.NewValue);
        }
    }

    private void ApplyArmed(bool armed)
    {
        Label.Text = armed ? "Listening" : "Hold to talk";
        Face.Style = (Style)Application.Current.Resources[armed ? "StudioButtonArmed" : "StudioButtonPrimary"];
        Face.SetValue(AutomationProperties.NameProperty, armed ? "Listening — release to stop" : "Hold to talk");
        var brush = (Microsoft.UI.Xaml.Media.Brush)Application.Current.Resources[armed ? "HeirloomGoldBrush" : "HeirloomInkBrush"];
        Mic.Foreground = brush;
        Label.Foreground = brush;
    }

    private void OnPressed(object sender, PointerRoutedEventArgs e)
    {
        if (!e.GetCurrentPoint(Face).Properties.IsLeftButtonPressed)
        {
            return;
        }

        e.Handled = true;
        try
        {
            Face.CapturePointer(e.Pointer);
        }
        catch
        {
            // Button may already own the pointer; we keep the hold until release.
        }

        _pointerHeld = true;
        BeginHold();
    }

    private void OnReleased(object sender, PointerRoutedEventArgs e)
    {
        e.Handled = true;
        try
        {
            Face.ReleasePointerCapture(e.Pointer);
        }
        catch
        {
            // Capture may already be gone.
        }

        _pointerHeld = false;
        EndHoldIfIdle();
    }

    private void OnCanceled(object sender, PointerRoutedEventArgs e)
    {
        _pointerHeld = false;
        EndHoldIfIdle();
    }

    private void OnCaptureLost(object sender, PointerRoutedEventArgs e)
    {
        var point = e.GetCurrentPoint(Face);
        if (_pointerHeld && (point.IsInContact || point.Properties.IsLeftButtonPressed))
        {
            try
            {
                Face.CapturePointer(e.Pointer);
            }
            catch
            {
                // Hold continues; PointerReleased still arrives via AddHandler.
            }

            return;
        }

        _pointerHeld = false;
        EndHoldIfIdle();
    }

    private void OnKeyDownHold(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key is not (VirtualKey.Space or VirtualKey.Enter) || e.KeyStatus.WasKeyDown)
        {
            return;
        }

        e.Handled = true;
        _keyHeld = true;
        BeginHold();
    }

    private void OnKeyUpHold(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key is not (VirtualKey.Space or VirtualKey.Enter))
        {
            return;
        }

        e.Handled = true;
        _keyHeld = false;
        EndHoldIfIdle();
    }

    private void BeginHold()
    {
        if (IsArmed)
        {
            return;
        }

        IsArmed = true;
        Pressed?.Invoke(this, new RoutedEventArgs());
    }

    private void EndHoldIfIdle()
    {
        if (_pointerHeld || _keyHeld || !IsArmed)
        {
            return;
        }

        IsArmed = false;
        Released?.Invoke(this, new RoutedEventArgs());
    }

    private void ForceEnd()
    {
        _pointerHeld = false;
        _keyHeld = false;
        if (!IsArmed)
        {
            return;
        }

        IsArmed = false;
        Released?.Invoke(this, new RoutedEventArgs());
    }
}

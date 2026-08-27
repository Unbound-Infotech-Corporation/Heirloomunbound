using Heirloom.Services;
using Heirloom.ViewModels;
using Microsoft.UI.Input;
using Microsoft.UI.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Markup;
using Microsoft.UI.Xaml.Media;
using Windows.Foundation;

namespace Heirloom.Controls;

public sealed partial class DockRail : UserControl
{
    public event EventHandler<DockItem>? DocumentRequested;
    public event EventHandler<string>? EdgeDropped;
    public event EventHandler<double>? SizeChangedByUser;

    private bool _splitting;
    private bool _moving;
    private double _splitStart;
    private double _splitSize;
    private ItemsPanelTemplate? _verticalPanel;
    private ItemsPanelTemplate? _horizontalPanel;

    public DockRail()
    {
        InitializeComponent();
        Loaded += (_, _) =>
        {
            ThemeService.Changed += OnTheme;
            ApplyChrome();
        };
        Unloaded += (_, _) => ThemeService.Changed -= OnTheme;
        SizeChanged += (_, _) => RefreshTiles();
        Tiles.ContainerContentChanging += OnContainerChanging;
    }

    public object? ItemsSource
    {
        get => GetValue(ItemsSourceProperty);
        set => SetValue(ItemsSourceProperty, value);
    }

    public static readonly DependencyProperty ItemsSourceProperty =
        DependencyProperty.Register(nameof(ItemsSource), typeof(object), typeof(DockRail), new PropertyMetadata(null, OnItems));

    public string Edge
    {
        get => (string)GetValue(EdgeProperty);
        set => SetValue(EdgeProperty, value);
    }

    public static readonly DependencyProperty EdgeProperty =
        DependencyProperty.Register(nameof(Edge), typeof(string), typeof(DockRail), new PropertyMetadata("left", OnEdge));

    public string ActiveId
    {
        get => (string)GetValue(ActiveIdProperty);
        set => SetValue(ActiveIdProperty, value);
    }

    public static readonly DependencyProperty ActiveIdProperty =
        DependencyProperty.Register(nameof(ActiveId), typeof(string), typeof(DockRail), new PropertyMetadata("assistant", OnActive));

    private static void OnActive(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is DockRail rail)
        {
            rail.RefreshTiles();
        }
    }

    private static void OnItems(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is DockRail rail)
        {
            rail.Tiles.ItemsSource = e.NewValue;
        }
    }

    private static void OnEdge(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is DockRail rail)
        {
            rail.ApplyChrome();
        }
    }

    private void OnTheme() => DispatcherQueue.TryEnqueue(ApplyChrome);

    private void ApplyChrome()
    {
        var edge = Edge ?? "left";
        var horizontal = edge == "top";
        StartSplit.Visibility = edge == "right" ? Visibility.Visible : Visibility.Collapsed;
        EndSplit.Visibility = edge == "left" ? Visibility.Visible : Visibility.Collapsed;
        BottomSplit.Visibility = horizontal ? Visibility.Visible : Visibility.Collapsed;
        GripLabel.Text = ThemeService.DockLocked ? "Locked" : "Dock";
        Grip.Opacity = ThemeService.DockLocked ? 0.55 : 1;
        Tiles.ItemsPanel = horizontal ? HorizontalPanel() : VerticalPanel();
        ScrollViewer.SetHorizontalScrollBarVisibility(Tiles, horizontal ? ScrollBarVisibility.Auto : ScrollBarVisibility.Disabled);
        ScrollViewer.SetVerticalScrollBarVisibility(Tiles, horizontal ? ScrollBarVisibility.Disabled : ScrollBarVisibility.Auto);
        RefreshTiles();
    }

    private ItemsPanelTemplate VerticalPanel() =>
        _verticalPanel ??= (ItemsPanelTemplate)XamlReader.Load(
            """
            <ItemsPanelTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">
              <ItemsStackPanel Orientation="Vertical" />
            </ItemsPanelTemplate>
            """);

    private ItemsPanelTemplate HorizontalPanel() =>
        _horizontalPanel ??= (ItemsPanelTemplate)XamlReader.Load(
            """
            <ItemsPanelTemplate xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">
              <StackPanel Orientation="Horizontal" />
            </ItemsPanelTemplate>
            """);

    private void OnContainerChanging(ListViewBase sender, ContainerContentChangingEventArgs args)
    {
        if (args.ItemContainer is ListViewItem)
        {
            RefreshOne(args.ItemContainer, args.Item as DockItem);
        }
    }

    private void RefreshTiles()
    {
        for (var i = 0; i < Tiles.Items.Count; i++)
        {
            RefreshOne(Tiles.ContainerFromIndex(i), Tiles.Items[i] as DockItem);
        }
    }

    private void RefreshOne(DependencyObject? container, DockItem? item)
    {
        if (container is not ListViewItem tile || tile.ContentTemplateRoot is not Grid grid || item is null)
        {
            return;
        }

        Image? image = null;
        FontIcon? icon = null;
        TextBlock? label = null;
        foreach (var child in grid.Children)
        {
            switch (child)
            {
                case Image img:
                    image = img;
                    break;
                case FontIcon font:
                    icon = font;
                    break;
                case TextBlock text:
                    label = text;
                    break;
            }
        }

        if (item.IsHeader)
        {
            tile.MinHeight = 22;
            tile.IsHitTestVisible = false;
            tile.IsTabStop = false;
            if (icon is not null)
            {
                icon.Visibility = Visibility.Collapsed;
            }

            if (image is not null)
            {
                image.Visibility = Visibility.Collapsed;
            }

            if (label is not null)
            {
                label.Visibility = Visibility.Visible;
                label.FontSize = 10;
                                label.FontWeight = FontWeights.SemiBold;
                label.CharacterSpacing = 140;
                label.Foreground = (Brush)Application.Current.Resources["HeirloomTextMutedBrush"];
            }

            ToolTipService.SetToolTip(tile, null);
            tile.Background = null;
            tile.BorderThickness = new Thickness(0);
            tile.PointerEntered -= OnTileEntered;
            tile.PointerExited -= OnTileExited;
            return;
        }

        tile.MinHeight = 36;
        tile.IsHitTestVisible = true;
        tile.IsTabStop = true;
        var here = string.Equals(item.Id, ActiveId, StringComparison.OrdinalIgnoreCase);
        tile.Background = here
            ? (Brush)Application.Current.Resources["HeirloomBgElevatedBrush"]
            : null;
        tile.BorderBrush = here
            ? (Brush)Application.Current.Resources["HeirloomGoldBrush"]
            : null;
        tile.BorderThickness = here
            ? Edge == "top" ? new Thickness(0, 0, 0, 2) : new Thickness(2, 0, 0, 0)
            : new Thickness(0);
        var showIcons = ThemeService.ShowIcons;
        var showLabels = Edge == "top" || ThemeService.ShowDockLabels(ActualWidth > 8 ? ActualWidth : ThemeService.DockSize);
        if (label is not null)
        {
            label.FontSize = 13;
            label.CharacterSpacing = 0;
            label.Foreground = (Brush)Application.Current.Resources["HeirloomTextBrush"];
        }

        if (icon is not null)
        {
            icon.Foreground = here
                ? (Brush)Application.Current.Resources["HeirloomGoldBrush"]
                : (Brush)Application.Current.Resources["HeirloomTextSecondaryBrush"];
        }

        var custom = ThemeService.TryGetButton("dock-" + item.Id);
        if (image is not null)
        {
            if (custom is not null && showIcons)
            {
                image.Source = custom;
                image.Visibility = Visibility.Visible;
                if (icon is not null)
                {
                    icon.Visibility = Visibility.Collapsed;
                }
            }
            else
            {
                image.Visibility = Visibility.Collapsed;
                if (icon is not null)
                {
                    icon.Visibility = showIcons ? Visibility.Visible : Visibility.Collapsed;
                }
            }
        }
        else if (icon is not null)
        {
            icon.Visibility = showIcons ? Visibility.Visible : Visibility.Collapsed;
        }

        if (label is not null)
        {
            label.Visibility = showLabels ? Visibility.Visible : Visibility.Collapsed;
        }

        ToolTipService.SetToolTip(tile, item.Label);
        tile.PointerEntered -= OnTileEntered;
        tile.PointerExited -= OnTileExited;
        tile.PointerEntered += OnTileEntered;
        tile.PointerExited += OnTileExited;
    }

    private void OnTileEntered(object sender, PointerRoutedEventArgs e)
    {
        if (sender is ListViewItem { Content: DockItem item } && !item.IsHeader)
        {
            StudioHelp.Hover(item.Id);
        }
    }

    private void OnTileExited(object sender, PointerRoutedEventArgs e)
    {
        if (sender is ListViewItem { Content: DockItem item } && !item.IsHeader)
        {
            StudioHelp.Leave(item.Id);
        }
    }

    private void OnItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is DockItem item && !item.IsHeader)
        {
            DocumentRequested?.Invoke(this, item);
        }
    }

    private void OnGripPressed(object sender, PointerRoutedEventArgs e)
    {
        if (ThemeService.DockLocked)
        {
            return;
        }

        _moving = true;
        Grip.CapturePointer(e.Pointer);
        e.Handled = true;
    }

    private void OnGripMoved(object sender, PointerRoutedEventArgs e)
    {
        if (_moving)
        {
            e.Handled = true;
        }
    }

    private void OnGripReleased(object sender, PointerRoutedEventArgs e)
    {
        if (!_moving)
        {
            return;
        }

        _moving = false;
        Grip.ReleasePointerCapture(e.Pointer);
        var window = XamlRoot?.Content as FrameworkElement ?? this;
        var pos = e.GetCurrentPoint(window).Position;
        var w = Math.Max(1, window.ActualWidth);
        var edge = pos.Y < 88 ? "top" : pos.X > w * 0.62 ? "right" : "left";
        EdgeDropped?.Invoke(this, edge);
        e.Handled = true;
    }

    private void OnSplitPressed(object sender, PointerRoutedEventArgs e)
    {
        _splitting = true;
        var pt = e.GetCurrentPoint(this).Position;
        _splitStart = Edge == "top" ? pt.Y : pt.X;
        _splitSize = Edge == "top" ? ActualHeight : ActualWidth;
        ((UIElement)sender).CapturePointer(e.Pointer);
        ProtectedCursor = InputSystemCursor.Create(
            Edge == "top" ? InputSystemCursorShape.SizeNorthSouth : InputSystemCursorShape.SizeWestEast);
        e.Handled = true;
    }

    private void OnSplitMoved(object sender, PointerRoutedEventArgs e)
    {
        if (!_splitting)
        {
            return;
        }

        var pt = e.GetCurrentPoint(this).Position;
        var next = Edge switch
        {
            "top" => _splitSize + (pt.Y - _splitStart),
            "right" => _splitSize + (_splitStart - pt.X),
            _ => _splitSize + (pt.X - _splitStart),
        };
        SizeChangedByUser?.Invoke(this, Math.Clamp(next, 56, 280));
        e.Handled = true;
    }

    private void OnSplitReleased(object sender, PointerRoutedEventArgs e)
    {
        _splitting = false;
        ((UIElement)sender).ReleasePointerCapture(e.Pointer);
        ProtectedCursor = null;
        e.Handled = true;
    }
}

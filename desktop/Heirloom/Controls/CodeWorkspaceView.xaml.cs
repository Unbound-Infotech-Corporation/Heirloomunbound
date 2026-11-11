using Heirloom.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace Heirloom.Controls;

public sealed partial class CodeWorkspaceView : UserControl
{
    private readonly CodeWorkspaceModel _model = new();

    public CodeWorkspaceView()
    {
        InitializeComponent();
        _model.UseCoder(["qwen2.5-coder:7b"]);
        CoderLine.Text = _model.Coder;
        _model.Open(["README.md", "src/main.py", ".env"]);
        Files.ItemsSource = _model.Files.ToList();
        _model.Propose("alpha\n", "beta\n");
        Hunks.ItemsSource = _model.Hunks.ToList();
        Term.Text = _model.CommandDetail;
        Loaded += OnLoaded;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        var path = Path.Combine(AppContext.BaseDirectory, "Assets", "code", "editor.html");
        if (!File.Exists(path))
        {
            return;
        }

        try
        {
            Monaco.Source = new Uri(path);
            Editor.Visibility = Visibility.Collapsed;
        }
        catch
        {
            Editor.Visibility = Visibility.Visible;
        }
    }

    private void OnFile(object sender, SelectionChangedEventArgs e)
    {
        if (Files.SelectedItem is string name)
        {
            Editor.Text = name;
        }
    }

    private void OnAccept(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string id })
        {
            var hunk = _model.Hunks.FirstOrDefault(item => item.Id == id);
            if (hunk is not null)
            {
                hunk.Accepted = true;
            }
        }

        Editor.Text = _model.ApplyAccepted();
    }

    private void OnRun(object sender, RoutedEventArgs e)
    {
        _model.ReviewCommand(Command.Text, approved: true);
        Term.Text = _model.CommandDetail;
    }

    private void OnGit(object sender, RoutedEventArgs e)
    {
        _model.ShowGit([" M README.md", "?? src/new.py"]);
        Term.Text = _model.GitDetail;
    }

    private void OnCommit(object sender, RoutedEventArgs e)
    {
        Term.Text = "Commit waits until you confirm the message in this document.";
    }

    private void OnAgent(object sender, RoutedEventArgs e)
    {
        Term.Text = string.Join("  ·  ", _model.AgentSteps) + "  ·  " + _model.Coder;
    }
}

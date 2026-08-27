namespace Heirloom.Services;

public static class StudioPickers
{
    public static async Task<string?> CopyAsync(IReadOnlyList<string> types, string destDirectory, string stem, bool pictures)
    {
        var file = await PickAsync(types, pictures).ConfigureAwait(true);
        if (file is null)
        {
            return null;
        }

        Directory.CreateDirectory(destDirectory);
        var dest = Path.Combine(destDirectory, stem + Path.GetExtension(file.Path));
        using var src = await file.OpenStreamForReadAsync().ConfigureAwait(true);
        await using var dst = File.Create(dest);
        await src.CopyToAsync(dst).ConfigureAwait(true);
        return dest;
    }

    public static async Task<IReadOnlyList<string>> CopyManyAsync(IReadOnlyList<string> types, string destDirectory, bool pictures)
    {
        Directory.CreateDirectory(destDirectory);
        var filter = pictures
            ? "Photographs\0*.jpg;*.jpeg;*.png;*.webp;*.bmp\0JPEG\0*.jpg;*.jpeg\0PNG\0*.png\0\0"
            : "Video\0*.mp4;*.mov;*.mkv;*.webm;*.wmv\0\0";
        try
        {
            var native = NativeOpenFile.Pick(
                global::Heirloom.App.WindowHandle,
                pictures ? "Add photos of you" : "File sitting",
                filter,
                multi: pictures);
            if (native is { Count: > 0 })
            {
                return CopyLocal(native, destDirectory);
            }

            if (native is not null)
            {
                return [];
            }
        }
        catch
        {
            // Fall through to the WinRT picker used by Photos.
        }

        var path = await CopyAsync(types, destDirectory, Guid.NewGuid().ToString("N"), pictures).ConfigureAwait(true);
        return string.IsNullOrWhiteSpace(path) ? [] : [path];
    }

    private static List<string> CopyLocal(IReadOnlyList<string> sources, string destDirectory)
    {
        var paths = new List<string>();
        foreach (var source in sources)
        {
            var dest = Path.Combine(destDirectory, Guid.NewGuid().ToString("N") + Path.GetExtension(source));
            File.Copy(source, dest, overwrite: true);
            paths.Add(dest);
        }

        return paths;
    }

    public static async Task<string?> ReadTextAsync(IReadOnlyList<string> types)
    {
        var file = await PickAsync(types, pictures: false).ConfigureAwait(true);
        if (file is null)
        {
            return null;
        }

        using var stream = await file.OpenStreamForReadAsync().ConfigureAwait(true);
        using var reader = new StreamReader(stream);
        return await reader.ReadToEndAsync().ConfigureAwait(true);
    }

    public static async Task<string?> PickFolderAsync(string title)
    {
        try
        {
            var native = NativeOpenFile.PickFolder(global::Heirloom.App.WindowHandle, title);
            if (native is not null)
            {
                return string.IsNullOrWhiteSpace(native) ? null : native;
            }
        }
        catch
        {
            // Fall through to the WinRT folder picker.
        }

        var picker = new Windows.Storage.Pickers.FolderPicker();
        picker.SuggestedStartLocation = Windows.Storage.Pickers.PickerLocationId.ComputerFolder;
        picker.FileTypeFilter.Add("*");
        WinRT.Interop.InitializeWithWindow.Initialize(picker, global::Heirloom.App.WindowHandle);
        var folder = await picker.PickSingleFolderAsync();
        return folder?.Path;
    }

    public static async Task<string?> PickSaveMp4Async(string suggestedName)
    {
        var picker = new Windows.Storage.Pickers.FileSavePicker();
        picker.SuggestedStartLocation = Windows.Storage.Pickers.PickerLocationId.VideosLibrary;
        picker.FileTypeChoices.Add("MPEG-4", [".mp4"]);
        picker.SuggestedFileName = string.IsNullOrWhiteSpace(suggestedName) ? "heirloom-film" : suggestedName;
        WinRT.Interop.InitializeWithWindow.Initialize(picker, global::Heirloom.App.WindowHandle);
        var dest = await picker.PickSaveFileAsync();
        return dest?.Path;
    }

    public static void OpenFolder(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        Directory.CreateDirectory(path);
        System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(path)
        {
            UseShellExecute = true,
        });
    }

    private static Windows.Storage.Pickers.FileOpenPicker CreatePicker(IReadOnlyList<string> types, bool pictures)
    {
        var picker = new Windows.Storage.Pickers.FileOpenPicker();
        picker.SuggestedStartLocation = pictures
            ? Windows.Storage.Pickers.PickerLocationId.PicturesLibrary
            : Windows.Storage.Pickers.PickerLocationId.DocumentsLibrary;
        picker.ViewMode = pictures
            ? Windows.Storage.Pickers.PickerViewMode.Thumbnail
            : Windows.Storage.Pickers.PickerViewMode.List;
        foreach (var type in types)
        {
            picker.FileTypeFilter.Add(type);
        }

        WinRT.Interop.InitializeWithWindow.Initialize(picker, global::Heirloom.App.WindowHandle);
        return picker;
    }

    private static async Task<Windows.Storage.StorageFile?> PickAsync(IReadOnlyList<string> types, bool pictures)
    {
        return await CreatePicker(types, pictures).PickSingleFileAsync();
    }
}

using System.Runtime.InteropServices;

namespace Heirloom.Services;

internal static class NativeOpenFile
{
    private const int OfnExplorer = 0x00080000;
    private const int OfnFileMustExist = 0x00001000;
    private const int OfnPathMustExist = 0x00000800;
    private const int OfnAllowMultiSelect = 0x00000200;
    private const int OfnNoChangeDir = 0x00000008;
    private const int OfnHideReadOnly = 0x00000004;
    private const int MaxFile = 32768;

    public static IReadOnlyList<string>? Pick(nint hwnd, string title, string filter, bool multi)
    {
        try
        {
            var shell = PickShell(hwnd, title, folders: false, multi);
            if (shell is not null)
            {
                return shell;
            }
        }
        catch
        {
            // Fall through to GetOpenFileName.
        }

        var buffer = Marshal.AllocHGlobal(MaxFile * 2);
        var filterPtr = AllocDoubleNull(filter);
        var titlePtr = Marshal.StringToHGlobalUni(title);
        try
        {
            for (var i = 0; i < MaxFile * 2; i++)
            {
                Marshal.WriteByte(buffer, i, 0);
            }

            var ofn = new OpenFileName
            {
                lStructSize = Marshal.SizeOf<OpenFileName>(),
                hwndOwner = hwnd,
                lpstrFilter = filterPtr,
                lpstrFile = buffer,
                nMaxFile = MaxFile,
                lpstrTitle = titlePtr,
                Flags = OfnExplorer | OfnFileMustExist | OfnPathMustExist | OfnNoChangeDir | OfnHideReadOnly
                    | (multi ? OfnAllowMultiSelect : 0),
            };

            if (!GetOpenFileNameW(ref ofn))
            {
                return CommDlgExtendedError() == 0 ? [] : null;
            }

            return Parse(buffer);
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
            Marshal.FreeHGlobal(filterPtr);
            Marshal.FreeHGlobal(titlePtr);
        }
    }

    private static nint AllocDoubleNull(string filter)
    {
        var chars = filter.ToCharArray();
        var ptr = Marshal.AllocHGlobal((chars.Length + 1) * 2);
        Marshal.Copy(chars, 0, ptr, chars.Length);
        Marshal.WriteInt16(ptr, chars.Length * 2, 0);
        return ptr;
    }

    private static List<string> Parse(nint buffer)
    {
        var parts = new List<string>();
        var offset = 0;
        while (true)
        {
            var chunk = Marshal.PtrToStringUni(buffer + offset);
            if (string.IsNullOrEmpty(chunk))
            {
                break;
            }

            parts.Add(chunk);
            offset += (chunk.Length + 1) * 2;
        }

        if (parts.Count == 0)
        {
            return [];
        }

        if (parts.Count == 1)
        {
            return File.Exists(parts[0]) ? parts : [];
        }

        var folder = parts[0];
        var files = new List<string>();
        for (var i = 1; i < parts.Count; i++)
        {
            var path = Path.Combine(folder, parts[i]);
            if (File.Exists(path))
            {
                files.Add(path);
            }
        }

        return files;
    }

    public static string? PickFolder(nint hwnd, string title)
    {
        try
        {
            var shell = PickShell(hwnd, title, folders: true, multi: false);
            if (shell is not null)
            {
                return shell.Count == 0 ? "" : shell[0];
            }
        }
        catch
        {
            // Folder dialog unavailable.
        }

        return null;
    }

    private static List<string>? PickShell(nint hwnd, string title, bool folders, bool multi)
    {
        var type = Type.GetTypeFromCLSID(new Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7"));
        if (type is null)
        {
            return null;
        }

        if (Activator.CreateInstance(type) is not IFileOpenDialog dialog)
        {
            return null;
        }

        uint options = FosForceFileSystem | FosNoChangeDir;
        if (folders)
        {
            options |= FosPickFolders;
        }
        else
        {
            options |= FosPathMustExist | FosFileMustExist;
            if (multi)
            {
                options |= FosAllowMultiSelect;
            }
        }

        dialog.SetOptions(options);
        dialog.SetTitle(title);
        var hr = dialog.Show(hwnd);
        if (hr != 0)
        {
            return hr == HresultCancelled ? [] : null;
        }

        var paths = new List<string>();
        if (multi && !folders)
        {
            dialog.GetResults(out var items);
            items.GetCount(out var count);
            for (uint i = 0; i < count; i++)
            {
                items.GetItemAt(i, out var item);
                item.GetDisplayName(SigdnFileSysPath, out var path);
                if (!string.IsNullOrWhiteSpace(path) && File.Exists(path))
                {
                    paths.Add(path);
                }
            }
        }
        else
        {
            dialog.GetResult(out var item);
            item.GetDisplayName(SigdnFileSysPath, out var path);
            if (!string.IsNullOrWhiteSpace(path) && (folders ? Directory.Exists(path) : File.Exists(path)))
            {
                paths.Add(path);
            }
        }

        return paths;
    }

    private const uint FosPickFolders = 0x20;
    private const uint FosForceFileSystem = 0x40;
    private const uint FosNoChangeDir = 0x8;
    private const uint FosAllowMultiSelect = 0x200;
    private const uint FosPathMustExist = 0x800;
    private const uint FosFileMustExist = 0x1000;
    private const uint SigdnFileSysPath = 0x80058000;
    private const int HresultCancelled = unchecked((int)0x800704C7);

    [ComImport]
    [Guid("d57c7288-d4ad-4768-be02-9d969532d960")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IFileOpenDialog
    {
        [PreserveSig] int Show(nint parent);
        void SetFileTypes(uint cFileTypes, nint rgFilterSpec);
        void SetFileTypeIndex(uint iFileType);
        void GetFileTypeIndex(out uint piFileType);
        void Advise(nint pfde, out uint pdwCookie);
        void Unadvise(uint dwCookie);
        void SetOptions(uint fos);
        void GetOptions(out uint pfos);
        void SetDefaultFolder(IShellItem psi);
        void SetFolder(IShellItem psi);
        void GetFolder(out IShellItem ppsi);
        void GetCurrentSelection(out IShellItem ppsi);
        void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string pszName);
        void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string pszTitle);
        void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string pszText);
        void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string pszLabel);
        void GetResult(out IShellItem ppsi);
        void AddPlace(IShellItem psi, int fdap);
        void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string pszDefaultExtension);
        void Close(int hr);
        void SetClientGuid(ref Guid guid);
        void ClearClientData();
        void SetFilter(nint pFilter);
        void GetResults(out IShellItemArray ppenum);
        void GetSelectedItems(out IShellItemArray ppsai);
    }

    [ComImport]
    [Guid("b63ea76d-1f85-456f-a19c-48159efa858b")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellItemArray
    {
        void BindToHandler(nint pbc, ref Guid bhid, ref Guid riid, out nint ppvOut);
        void GetPropertyStore(int flags, ref Guid riid, out nint ppv);
        void GetPropertyDescriptionList(nint keyType, ref Guid riid, out nint ppv);
        void GetAttributes(int attribFlags, uint sfgaoMask, out uint psfgaoAttribs);
        void GetCount(out uint pdwNumItems);
        void GetItemAt(uint dwIndex, out IShellItem ppsi);
        void EnumItems(out nint ppenumShellItems);
    }

    [ComImport]
    [Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellItem
    {
        void BindToHandler(nint pbc, ref Guid bhid, ref Guid riid, out nint ppv);
        void GetParent(out IShellItem ppsi);
        void GetDisplayName(uint sigdnName, [MarshalAs(UnmanagedType.LPWStr)] out string ppszName);
        void GetAttributes(uint sfgaoMask, out uint psfgaoAttribs);
        void Compare(IShellItem psi, uint hint, out int piOrder);
    }

    [DllImport("comdlg32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool GetOpenFileNameW(ref OpenFileName ofn);

    [DllImport("comdlg32.dll")]
    private static extern int CommDlgExtendedError();

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct OpenFileName
    {
        public int lStructSize;
        public nint hwndOwner;
        public nint hInstance;
        public nint lpstrFilter;
        public nint lpstrCustomFilter;
        public int nMaxCustFilter;
        public int nFilterIndex;
        public nint lpstrFile;
        public int nMaxFile;
        public nint lpstrFileTitle;
        public int nMaxFileTitle;
        public nint lpstrInitialDir;
        public nint lpstrTitle;
        public int Flags;
        public short nFileOffset;
        public short nFileExtension;
        public nint lpstrDefExt;
        public nint lCustData;
        public nint lpfnHook;
        public nint lpTemplateName;
        public nint pvReserved;
        public int dwReserved;
        public int FlagsEx;
    }
}

#!/bin/sh
# Real-device check of docker/ncc-storage's format core on loop devices (they are not USB, so
# this sources the helper and calls format_disk directly; the USB check stays in cmd_format_usb).
# Run as root in a privileged container with the helper's packages (+ fdisk):
#   docker run --rm --privileged -v "$PWD:/src:ro" --entrypoint sh --user 0 ncc:test /src/tests/hardware/format_loop.sh
set -u
. /src/docker/ncc-storage
set +e # the helper sets -e; the checks below handle failures themselves
DEVDIR=/run/ncc-root/dev
W=/var/tmp/fmt
mkdir -p "$W" /mnt/t
FAIL=0
ok() { printf 'PASS %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1"; FAIL=1; }

mkloop() { # file size
    rm -f "$1"
    truncate -s "$2" "$1"
    losetup -f --show -P "$1"
}

verify() { # name disk fs expect_label expect_table expect_ptype
    disk=$1 fs=$2 label=$3 table=$4
    d=/dev/$disk
    [ -e "$d" ] || mknod "$d" b "$(cat /sys/class/block/$disk/dev | cut -d: -f1)" "$(cat /sys/class/block/$disk/dev | cut -d: -f2)"
    t=$(sfdisk -d "$d" | sed -n 's/^label: //p')
    np=$(ls -d /sys/class/block/$disk/$disk*/ 2>/dev/null | wc -l)
    pn=$(ls -d /sys/class/block/$disk/$disk*/ | head -n1 | xargs basename)
    node=$DEVDIR/$pn
    [ -e "$node" ] || mknod "$node" b "$(cut -d: -f1 /sys/class/block/$pn/dev)" "$(cut -d: -f2 /sys/class/block/$pn/dev)"
    ty=$(blkid -o value -s TYPE -p "$node")
    lb=$(blkid -o value -s LABEL -p "$node")
    [ "$t" = "$table" ] && [ "$np" = 1 ] || { bad "$fs table=$t parts=$np"; return; }
    case $fs in exfat) et=exfat ;; fat32) et=vfat ;; ntfs) et=ntfs ;; ext4) et=ext4 ;; esac
    [ "$ty" = "$et" ] || { bad "$fs blkid type=$ty"; return; }
    [ "$lb" = "$label" ] || { bad "$fs label=$lb want $label"; return; }
    case $fs in ntfs) drv=ntfs3 ;; fat32) drv=vfat ;; *) drv=$fs ;; esac
    mount -t "$drv" "$node" /mnt/t || { bad "$fs mount"; return; }
    echo hi >/mnt/t/x && [ "$(cat /mnt/t/x)" = hi ] && ok "$fs/$table mount+write ($(sfdisk -d "$d" | grep -o 'type=[^,]*' | head -n1), $(df -h /mnt/t | tail -n1 | awk '{print $2}'))" || bad "$fs write"
    umount /mnt/t
}

# fmt <disk> <majmin> <bytes> <fs> [label]; the disk's real diskseq is added unless $SEQ is set
fmt() { d=$1 m=$2 b=$3; shift 3; ( format_disk "$d" "$m" "$b" "${SEQ:-$(cat /sys/class/block/$d/diskseq 2>/dev/null)}" "$@" ) >"$W/out" 2>&1; }
sig() { # disk: every partition's blkid signature + the partition table
    for p in $(fmt_parts "$1"); do echo "$p $(blkid -p -o export "$(fmt_node "$p")" | sort | tr '\n' ' ')"; done
    sfdisk -d "/dev/$1" 2>/dev/null
}
mk2() { # file -> loop with two ext4 partitions (distinct labels); sets dev, n, mm, pn1, pn2
    dev=$(mkloop "$1" 1G); n=${dev##*/}
    printf 'label: dos\nstart=2048,size=300MiB,type=83\nsize=300MiB,type=83\n' | sfdisk -q "$dev"
    partx -u "$dev" 2>/dev/null; sleep 1
    pn1=$(fmt_node "${n}p1"); pn2=$(fmt_node "${n}p2")
    mkfs.ext4 -q -F -L SIB1 "$pn1"; mkfs.ext4 -q -F -L SIB2 "$pn2"
    mm=$(cat /sys/class/block/$n/dev)
}
running() { # exact process name (/proc comm), or "sleep30" for the shims' hung stage
    for d in /proc/[0-9]*; do
        [ "$(cat "$d/comm" 2>/dev/null)" = "${1%30}" ] || continue
        case $1 in *30) [ "$(tr '\0' ' ' <"$d/cmdline")" = "sleep 30 " ] || continue ;; esac
        return 0
    done
    return 1
}
mkdir -p "$W/bin"
for t in wipefs sfdisk mkfs.exfat; do
    real=$(command -v $t)
    printf '#!/bin/sh\n[ "${SLOW_TOOL:-}" != %s ] || exec sleep 30\n[ "${DELAY_TOOL:-}" != %s ] || sleep 4\nexec %s "$@"\n' "$t" "$t" "$real" >"$W/bin/$t"
    chmod +x "$W/bin/$t"
done
PATH=$W/bin:$PATH

cleanup() { losetup -D 2>/dev/null; rm -rf "$W"; }
trap cleanup EXIT

echo "== blank 1G, MBR, all filesystems"
for fs in exfat fat32 ntfs ext4; do
    dev=$(mkloop "$W/a.img" 1G); n=${dev##*/}
    mm=$(cat /sys/class/block/$n/dev)
    lbl=TEST1
    fmt "$n" "$mm" 1073741824 "$fs" "$lbl" && verify "$n" "$fs" "$lbl" dos || { bad "$fs blank: $(cat $W/out)"; }
    losetup -d "$dev"
done

echo "== existing multi-partition MBR (ext4+exfat+garbage) -> exfat, no label"
dev=$(mkloop "$W/b.img" 1G); n=${dev##*/}
printf 'label: dos\nstart=2048,size=300MiB,type=83\nsize=300MiB,type=7\ntype=c\n' | sfdisk -q "$dev"
partx -u "$dev" 2>/dev/null; sleep 1
for p in $(fmt_parts "$n"); do pn=$(fmt_node "$p"); mkfs.ext4 -q -F "$pn" 2>/dev/null; done
before=$(fmt_parts "$n" | wc -l)
mm=$(cat /sys/class/block/$n/dev)
fmt "$n" "$mm" 1073741824 exfat "" && verify "$n" exfat "" dos || bad "multi: $(cat $W/out)"
echo "   partitions before=$before"
losetup -d "$dev"

echo "== GPT (2.1T sparse), exfat/ntfs/ext4 (fat32 is refused there, see (e))"
for fs in exfat ntfs ext4; do
    dev=$(mkloop "$W/c.img" 2200G); n=${dev##*/}
    mm=$(cat /sys/class/block/$n/dev)
    sz=$(( $(cat /sys/class/block/$n/size) * 512 ))
    lbl="My Disk"
    fmt "$n" "$mm" "$sz" "$fs" "$lbl" && verify "$n" "$fs" "$lbl" gpt || bad "$fs gpt: $(cat $W/out)"
    losetup -d "$dev"
    rm -f "$W/c.img"
done

echo "== GPT disk re-formatted as MBR-size? (existing GPT, 1G) -> ext4"
dev=$(mkloop "$W/d.img" 1G); n=${dev##*/}
printf 'label: gpt\nstart=2048,size=100MiB\nsize=100MiB\n' | sfdisk -q "$dev"; partx -u "$dev" 2>/dev/null; sleep 1
mm=$(cat /sys/class/block/$n/dev)
fmt "$n" "$mm" 1073741824 ext4 DATA && verify "$n" ext4 DATA dos || bad "gpt->dos: $(cat $W/out)"
losetup -d "$dev"

echo "== refusals"
dev=$(mkloop "$W/e.img" 1G); n=${dev##*/}
mm=$(cat /sys/class/block/$n/dev)
fmt "$n" "$mm" 1073741824 ext4 A || bad "setup"
pn=$(fmt_parts "$n" | head -n1); node=$(fmt_node "$pn")
mount -t ext4 "$node" /mnt/t
fmt "$n" "$mm" 1073741824 exfat X && bad "mounted partition not refused" || { grep -q 'in use' "$W/out" && ok "refuse: partition mounted ($(cat $W/out))" || bad "mounted msg: $(cat $W/out)"; }
SEQ=1 fmt "$pn" "$(cat /sys/class/block/$pn/dev)" 1 exfat X && bad "partition accepted" || { grep -q partition "$W/out" && ok "refuse: partition target" || bad "part msg $(cat $W/out)"; }
umount /mnt/t
fmt "$n" 7:7 1073741824 exfat X && bad "wrong majmin accepted" || { grep -q 'device numbers' "$W/out" && ok "refuse: wrong maj:min" || bad "mm msg"; }
fmt "$n" "$mm" 1073741823 exfat X && bad "wrong size accepted" || { grep -q 'size changed' "$W/out" && ok "refuse: wrong size" || bad "sz msg"; }
fmt "$n" "$mm" 1073741824 exfat 'a;b' && bad "bad label accepted" || { grep -q 'invalid label' "$W/out" && ok "refuse: bad label" || bad "lbl msg"; }
fmt "$n" "$mm" 1073741824 exfat 'ABCDEFGHIJKLMNOP' && bad "long label accepted" || ok "refuse: label too long"
fmt "$n" "$mm" 1073741824 xfs X && bad "xfs accepted" || ok "refuse: fs"
# still intact after all refusals
[ "$(blkid -o value -s TYPE -p "$node")" = ext4 ] && ok "disk untouched after refusals" || bad "disk changed by refusal"
(cmd_format_usb "$n" "$mm" 1073741824 "$(cat /sys/class/block/$n/diskseq)" exfat X) >"$W/out" 2>&1; grep -q 'not a USB disk' "$W/out" && ok "production entry refuses non-USB loop" || bad "usb check: $(cat $W/out)"
losetup -d "$dev"


echo "== (a) sibling partition mounted in ANOTHER mount namespace -> refused before any write"
mk2 "$W/g.img"
before=$(sig "$n"); h1=$(sha1sum <"$W/g.img")
mkdir -p /mnt/ns
unshare -m --propagation private sh -c "mount -t ext4 -o ro $pn2 /mnt/ns && exec sleep 600" &
nspid=$!; sleep 1
grep -q " /mnt/ns " /proc/self/mountinfo && bad "(a) setup: mount visible in our namespace" || ok "(a) setup: mount invisible to the helper's mountinfo"
fmt "$n" "$mm" 1073741824 exfat X && bad "(a) formatted with a foreign-namespace mount" || { grep -q 'in use' "$W/out" && ok "(a) refused: $(cat $W/out)" || bad "(a) msg: $(cat $W/out)"; }
kill $nspid 2>/dev/null; wait $nspid 2>/dev/null
[ "$(sig "$n")" = "$before" ] && [ "$(sha1sum <"$W/g.img")" = "$h1" ] && ok "(a) every partition signature and the whole image unchanged" || bad "(a) disk was modified"
losetup -d "$dev"

echo "== (b) holder (device-mapper linear on a partition) -> refused, nothing written"
mk2 "$W/h.img"
before=$(sig "$n"); h1=$(sha1sum <"$W/h.img")
if dmsetup create nccht --noudevsync --table "0 $(blockdev --getsz "$pn2") linear $(cat /sys/class/block/${n}p2/dev) 0" 2>"$W/dm.err"; then
    ls /sys/class/block/${n}p2/holders/ | grep -q . && ok "(b) setup: holder present ($(ls /sys/class/block/${n}p2/holders/))" || bad "(b) setup: no holder"
    fmt "$n" "$mm" 1073741824 exfat X && bad "(b) formatted a disk with a holder" || { grep -q 'device-mapper' "$W/out" && ok "(b) refused: $(cat $W/out)" || bad "(b) msg: $(cat $W/out)"; }
    dmsetup remove --force nccht
    [ "$(sig "$n")" = "$before" ] && [ "$(sha1sum <"$W/h.img")" = "$h1" ] && ok "(b) nothing written" || bad "(b) disk was modified"
else
    bad "(b) dmsetup unavailable: $(cat $W/dm.err)"
fi
losetup -d "$dev"

echo "== (c) diskseq mismatch (replugged identical stick) -> refused, nothing written"
mk2 "$W/i.img"
before=$(sig "$n"); h1=$(sha1sum <"$W/i.img")
SEQ=$(( $(cat /sys/class/block/$n/diskseq) + 1 )) fmt "$n" "$mm" 1073741824 exfat X && bad "(c) accepted wrong diskseq" || { grep -q 're-plugged' "$W/out" && ok "(c) refused: $(cat $W/out)" || bad "(c) msg: $(cat $W/out)"; }
[ "$(sig "$n")" = "$before" ] && [ "$(sha1sum <"$W/i.img")" = "$h1" ] && ok "(c) nothing written" || bad "(c) disk was modified"
losetup -d "$dev"

echo "== (d) two concurrent formats of one disk -> second refused by the lock"
dev=$(mkloop "$W/j.img" 1G); n=${dev##*/}; mm=$(cat /sys/class/block/$n/dev)
( DELAY_TOOL=wipefs fmt "$n" "$mm" 1073741824 exfat A ) &
a=$!; sleep 1.5
fmt_locked "$n" && ok "(d) lock held while first runs (mount/fsck would refuse)" || bad "(d) lock not held"
cp "$W/out" "$W/outA" 2>/dev/null
fmt "$n" "$mm" 1073741824 ext4 B && bad "(d) second format ran" || { grep -q 'already running' "$W/out" && ok "(d) second refused: $(cat $W/out)" || bad "(d) msg: $(cat $W/out)"; }
wait $a; sleep 0.5
fmt_locked "$n" && bad "(d) lock leaked after finish" || ok "(d) lock released after finish"
[ "$(blkid -o value -s TYPE -p "$(fmt_node "${n}p1")")" = exfat ] && ok "(d) first format completed intact" || bad "(d) first format result wrong"
losetup -d "$dev"

echo "== (e) FAT32 on >2 TiB -> refused, nothing written"
dev=$(mkloop "$W/k.img" 2200G); n=${dev##*/}; mm=$(cat /sys/class/block/$n/dev)
sz=$(( $(cat /sys/class/block/$n/size) * 512 )); h1=$(du -k "$W/k.img" | cut -f1) # sparse: allocated blocks
fmt "$n" "$mm" "$sz" fat32 X && bad "(e) fat32 accepted" || { grep -q '2 TB' "$W/out" && ok "(e) refused: $(cat $W/out)" || bad "(e) msg: $(cat $W/out)"; }
[ "$(du -k "$W/k.img" | cut -f1)" = "$h1" ] && ok "(e) nothing written (no blocks allocated)" || bad "(e) disk was modified"
losetup -d "$dev"; rm -f "$W/k.img"

echo "== (f) TERM during wipefs / sfdisk / mkfs -> prompt exit, lock released, no stray tools"
for tool in wipefs sfdisk mkfs.exfat; do
    dev=$(mkloop "$W/l.img" 1G); n=${dev##*/}; mm=$(cat /sys/class/block/$n/dev); sq=$(cat /sys/class/block/$n/diskseq)
    SLOW_TOOL=$tool sh -c ". /src/docker/ncc-storage; PATH=$W/bin:\$PATH; set +e; format_disk $n $mm 1073741824 $sq exfat X" >"$W/outf" 2>&1 &
    pid=$!; sleep 2
    running sleep30 || bad "(f) $tool: stage not running"
    t0=$(date +%s.%N); kill -TERM $pid; wait $pid; rc=$?; t1=$(date +%s.%N)
    el=$(echo "$t1 - $t0" | bc 2>/dev/null || echo "$t1 $t0" | awk '{print $1-$2}')
    running sleep30 && st=stray || st=clean
    fmt_locked "$n" && lk=held || lk=released
    awk -v e="$el" 'BEGIN{exit !(e<2)}' && [ $st = clean ] && [ $lk = released ] && grep -q cancelled "$W/outf" \
        && ok "(f) TERM in $tool: exit rc=$rc in ${el}s, children $st, lock $lk" || bad "(f) $tool: rc=$rc ${el}s $st lock $lk: $(cat $W/outf)"
    losetup -d "$dev"
done

[ $FAIL = 0 ] && echo ALL PASS || echo SOME FAILED
exit $FAIL

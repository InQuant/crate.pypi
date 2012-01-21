import os

from django.core.urlresolvers import reverse
from django.db import models
from django.db.models import Sum
from django.db.models.signals import post_save
from django.dispatch import receiver

from django_hstore import hstore
from model_utils import Choices
from model_utils.models import TimeStampedModel

from crate.fields import JSONField
from packages.utils import verlib


# @@@ These are by Nature Hierarchical. Would we benefit from a tree structure?
class TroveClassifier(models.Model):
    trove = models.CharField(max_length=350, unique=True)

    def __unicode__(self):
        return self.trove


class Package(TimeStampedModel):
    name = models.SlugField(max_length=150, unique=True)

    def __unicode__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("package_detail", kwargs={"name": self.name})

    @property
    def downloads(self):
        total_downloads = ReleaseFile.objects.filter(release__package__pk=self.pk).aggregate(total_downloads=Sum("downloads"))["total_downloads"]
        if total_downloads is None:
            return 0
        return total_downloads

    @property
    def latest(self):
        if not hasattr(self, "_latest_release"):
            releases = self.releases.order_by("-order")[:1]
            if releases:
                self._latest_release = releases[0]
            else:
                self._latest_release = None
        return self._latest_release

    @property
    def install_command(self):
        return "pip install %(package)s" % {"package": self.name}

    @property
    def requirement_line(self):
        if self.latest is not None:
            # @@@ Should This Be Major/Minor/Patch/Exact Version?
            #       For Now we'll use Minor if verlib can parse it, else exact
            normalized = verlib.suggest_normalized_version(self.latest.version)
            if normalized is not None:
                ver = str(verlib.NormalizedVersion(normalized))
                next_version = "%(major)s.%(minor)s" % {"major": ver.split(".")[0], "minor": int(ver.split(".")[1]) + 1}
                return "%(package)s>=%(current_version)s,<%(next_version)s" % {
                    "package": self.name,
                    "current_version": self.latest.version,
                    "next_version": next_version,
                }
            return "%(package)s==%(version)s" % {"package": self.name, "version": self.latest.version}


class Release(TimeStampedModel):
    package = models.ForeignKey(Package, related_name="releases")
    version = models.CharField(max_length=512)

    hidden = models.BooleanField(default=False)

    order = models.IntegerField(default=0)

    platform = models.TextField(blank=True)

    summary = models.TextField()
    description = models.TextField(blank=True)

    keywords = models.TextField(blank=True)

    license = models.TextField(blank=True)

    author = models.TextField(blank=True)
    author_email = models.TextField(blank=True)

    maintainer = models.TextField(blank=True)
    maintainer_email = models.TextField(blank=True)

    requires_python = models.CharField(max_length=25, blank=True)

    download_uri = models.URLField(max_length=1024, blank=True)
    uris = hstore.DictionaryField()

    classifiers = models.ManyToManyField(TroveClassifier, related_name="releases", blank=True)

    raw_data = JSONField(null=True)

    objects = hstore.Manager()

    class Meta:
        unique_together = ("package", "version")

    def __unicode__(self):
        return u"%(package)s %(version)s" % {"package": self.package.name, "version": self.version}

    @property
    def downloads(self):
        total_downloads = ReleaseFile.objects.filter(release__pk=self.pk).aggregate(total_downloads=Sum("downloads"))["total_downloads"]
        if total_downloads is None:
            return 0
        return total_downloads

    @property
    def install_command(self):
        return "pip install %(package)s==%(version)s" % {"package": self.package.name, "version": self.version}

    @property
    def requirement_line(self):
        # @@@ Should This Be Major/Minor/Patch/Exact Version?
        #       For Now we'll use Minor if verlib can parse it, else exact
        normalized = verlib.suggest_normalized_version(self.version)
        if normalized is not None:
            ver = str(verlib.NormalizedVersion(normalized))
            next_version = "%(major)s.%(minor)s" % {"major": ver.split(".")[0], "minor": int(ver.split(".")[1]) + 1}
            return "%(package)s>=%(current_version)s,<%(next_version)s" % {
                "package": self.package.name,
                "current_version": self.version,
                "next_version": next_version,
            }
        return "%(package)s==%(version)s" % {"package": self.package.name, "version": self.version}


class ReleaseFile(TimeStampedModel):

    TYPES = Choices(
        ("sdist", "Source"),
        ("bdist_egg", "Egg"),
        ("bdist_msi", "MSI"),
        ("bdist_dmg", "DMG"),
        ("bdist_rpm", "RPM"),
        ("bdist_dumb", "bdist_dumb"),
        ("bdist_wininst", "bdist_wininst"),
    )

    release = models.ForeignKey(Release, related_name="files")

    type = models.CharField(max_length=25, choices=TYPES)
    file = models.FileField(upload_to="packages", max_length=512)
    filename = models.CharField(max_length=200, help_text="This is the file name given to us by PyPI", blank=True, null=True, default=None)
    digest = models.CharField(max_length=512)

    python_version = models.CharField(max_length=25)

    downloads = models.PositiveIntegerField(default=0)
    comment = models.TextField(blank=True)

    class Meta:
        unique_together = ("release", "type", "python_version", "filename")

    def __unicode__(self):
        return os.path.basename(self.file.name)

    def get_python_version_display(self):
        if self.python_version.lower() == "source":
            return ""
        return self.python_version


class ReleaseRequire(models.Model):

    KIND = Choices(
        ("requires", "Requirement"),
        ("requires_dist", "Dist Requirement"),
        ("external", "External Requirement"),
    )

    release = models.ForeignKey(Release, related_name="requires")

    kind = models.CharField(max_length=50, choices=KIND)
    name = models.CharField(max_length=150)
    version = models.CharField(max_length=50)

    environment = models.TextField(blank=True)

    def __unicode__(self):
        return self.name


class ReleaseProvide(models.Model):

    KIND = Choices(
        ("provides", "Provides"),
        ("provides_dist", "Dist Provides"),
    )

    release = models.ForeignKey(Release, related_name="provides")

    kind = models.CharField(max_length=50, choices=KIND)
    name = models.CharField(max_length=150)
    version = models.CharField(max_length=50)

    environment = models.TextField(blank=True)

    def __unicode__(self):
        return self.name


class ReleaseObsolete(models.Model):

    KIND = Choices(
        ("obsoletes", "Obsoletes"),
        ("obsoletes_dist", "Dist Obsoletes"),
    )

    release = models.ForeignKey(Release, related_name="obsoletes")

    kind = models.CharField(max_length=50, choices=KIND)
    name = models.CharField(max_length=150)
    version = models.CharField(max_length=50)

    environment = models.TextField(blank=True)

    def __unicode__(self):
        return self.name


@receiver(post_save, sender=Release)
def version_ordering(sender, **kwargs):
    instance = kwargs.get("instance")
    if instance is not None and kwargs.get("created", True):
        releases = Release.objects.filter(package__pk=instance.package.pk)

        versions = []
        dated = []

        for release in releases:
            normalized = verlib.suggest_normalized_version(release.version)
            if normalized is not None:
                versions.append(release)
            else:
                dated.append(release)

        versions.sort(key=lambda x: verlib.NormalizedVersion(verlib.suggest_normalized_version(x.version)))
        dated.sort(key=lambda x: x.created)

        for i, release in enumerate(dated + versions):
            if release.order != i:
                Release.objects.filter(pk=release.pk).update(order=i)
